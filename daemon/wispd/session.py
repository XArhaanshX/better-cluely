"""The live session: transcript, answers, and the commands the UI sends.

Latency trick: when the other side finishes a sentence that looks like a
question, an answer starts generating straight away ("auto" answer). When
the user then presses Ask, that answer is already streaming or finished,
so it is shown at once instead of starting a new request. Pressing Ask a
second time asks fresh, with a screenshot.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime

from . import prompts
from .audio import AudioCapture, DeviceWatcher, echo_risk
from .config import DATA_DIR, Config
from .llm import BackendError, Request, make_backend
from .prompts import Line
from .screen import capture
from .stt import Transcriber, Utterance

log = logging.getLogger(__name__)

STATE_FILE = DATA_DIR / "state.json"
SESSIONS_DIR = DATA_DIR / "sessions"
# Settings the UI may change at runtime; they persist in state.json.
RUNTIME_KEYS = {"mode", "preset", "backend", "auto_answer", "capture_mic", "capture_system"}
SYSTEM_AUDIO_GATE = 0.0008  # the sink monitor is digital: silence is ~0
AUTO_MIN_GAP_S = 2.5
AUTO_FRESH_S = 45.0
# On loudspeakers the mic hears the other side. Mic audio quieter than
# this fraction of their level is treated as echo, not as the user.
ECHO_RATIO = 0.6
ECHO_DECAY = 0.92  # per 20 ms frame: the echo estimate fades over ~250 ms
LEVEL_HZ = 12


@dataclass
class Answer:
    id: str
    kind: str
    title: str
    auto: bool = False
    text: str = ""
    line_index: int | None = None
    started: float = field(default_factory=time.time)
    first_ms: int | None = None
    total_ms: int | None = None
    capture_ms: int | None = None
    done: bool = False
    cancelled: bool = False
    error: str | None = None
    shown: bool = False

    def public(self) -> dict:
        return asdict(self)


class Session:
    def __init__(self, cfg: Config, emit: Callable[[dict], None]):
        self.cfg = cfg
        self._emit = emit
        self._apply_saved_state()
        self.backend = make_backend(cfg)
        self.stt: Transcriber | None = None
        self.stt_error: str | None = None
        self.lines: list[Line] = []
        self.partial: dict[str, str] = {"you": "", "them": ""}
        self.answers: list[Answer] = []
        self.t0 = time.time()
        self.listening = False
        self.listen_started: float | None = None
        self._captures: dict[str, AudioCapture] = {}
        self._pumps: dict[str, asyncio.Task] = {}
        self._levels = {"you": 0.0, "them": 0.0}
        self._watcher: DeviceWatcher | None = None
        self._echo_risk = False
        self._them_env = 0.0
        self._tasks: dict[str, asyncio.Task] = {}
        self._bg: set[asyncio.Task] = set()
        self._last_auto = 0.0

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._prime_backend()
        await self.backend.start()
        self._spawn(self._load_stt())
        self._spawn(self._level_loop())

    async def close(self) -> None:
        await self.listen(False)
        for task in list(self._tasks.values()):
            task.cancel()
        self._save_session()
        if self.stt:
            self.stt.stop()
        await self.backend.close()

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return task

    def _prime_backend(self) -> None:
        set_system = getattr(self.backend, "set_system", None)
        if set_system:
            set_system(prompts.system_prompt(self.cfg.mode))

    async def _load_stt(self) -> None:
        loop = asyncio.get_running_loop()
        stt = Transcriber(self.cfg.stt_model_dir, self.cfg.stt_threads, self._on_utterance, loop)
        try:
            await loop.run_in_executor(None, stt.load)
        except Exception as e:
            log.exception("speech model failed to load")
            self.stt_error = f"Speech model failed to load: {e}"
            self._emit({"ev": "error", "message": self.stt_error})
            self._status()
            return
        stt.add_source("you", self.cfg.mic_gate)
        stt.add_source("them", SYSTEM_AUDIO_GATE)
        stt.start()
        self.stt = stt
        self._status()

    # -- listening ---------------------------------------------------------

    async def listen(self, on: bool) -> None:
        if on == self.listening:
            return
        if on:
            wanted = [s for s, enabled in (("you", self.cfg.capture_mic),
                                           ("them", self.cfg.capture_system)) if enabled]
            for source in wanted:
                await self._start_capture(source)
            self._watcher = DeviceWatcher(self._devices_changed)
            await self._watcher.start()
            self._echo_risk = echo_risk(self._watcher.sink)
            self.listening = True
            self.listen_started = time.time()
        else:
            self.listening = False
            self.listen_started = None
            if self._watcher:
                await self._watcher.stop()
                self._watcher = None
            for source in list(self._captures):
                await self._stop_capture(source)
                if self.stt:
                    self.stt.flush(source)
        self._status()

    async def _start_capture(self, source: str) -> None:
        cap = AudioCapture(source)
        await cap.start()
        self._captures[source] = cap
        self._pumps[source] = asyncio.create_task(self._pump(cap))

    async def _stop_capture(self, source: str) -> None:
        cap = self._captures.pop(source, None)
        pump = self._pumps.pop(source, None)
        if pump:
            pump.cancel()
        if cap:
            await cap.stop()

    async def _devices_changed(self, sink: str, source: str, old: tuple[str, str]) -> None:
        self._echo_risk = echo_risk(sink)
        if not self.listening:
            return
        if sink != old[0] and "them" in self._captures:
            await self._stop_capture("them")
            await self._start_capture("them")
        if source != old[1] and "you" in self._captures:
            await self._stop_capture("you")
            await self._start_capture("you")

    async def _pump(self, cap: AudioCapture) -> None:
        async for frame in cap.frames():
            rms = frame.rms
            if frame.source == "them":
                self._them_env = max(rms, self._them_env * ECHO_DECAY)
            elif self._echo_risk and rms < ECHO_RATIO * self._them_env:
                rms = 0.0  # speaker echo, not the user
            if frame.rms > self._levels[frame.source]:
                self._levels[frame.source] = frame.rms
            if self.stt:
                self.stt.push(frame.source, frame.samples, rms)
        # parec ended on its own (device gone, PipeWire restart): retry.
        if self.listening and self._captures.get(cap.source) is cap:
            log.info("restarting %s capture", cap.source)
            await asyncio.sleep(1.0)
            if self.listening and self._captures.get(cap.source) is cap:
                await cap.stop()
                self._captures.pop(cap.source, None)
                await self._start_capture(cap.source)

    async def _level_loop(self) -> None:
        while True:
            await asyncio.sleep(1 / LEVEL_HZ)
            if self.listening:
                lv = self._levels
                self._emit({"ev": "level", "you": round(lv["you"], 4), "them": round(lv["them"], 4)})
                lv["you"] = lv["them"] = 0.0

    def _on_utterance(self, u: Utterance) -> None:
        if not u.final:
            self.partial[u.source] = u.text
            self._emit({"ev": "partial", "source": u.source, "text": u.text})
            return
        self.partial[u.source] = ""
        line = Line(u.source, u.text, max(0.0, u.started - self.t0))
        self.lines.append(line)
        index = len(self.lines) - 1
        self._emit({"ev": "line", "n": index, "source": line.source, "text": line.text, "t": line.t})
        if line.source == "them" and self.cfg.auto_answer and prompts.looks_like_question(line.text):
            self._auto_answer(index)

    # -- answers -----------------------------------------------------------

    def _auto_answer(self, index: int) -> None:
        now = time.monotonic()
        running = [a for a in self.answers if a.auto and not a.done]
        if not running and now - self._last_auto < AUTO_MIN_GAP_S:
            return
        question = self.lines[index].text
        for a in running:
            # They kept talking: fold the earlier part into this question.
            if a.line_index is not None and a.line_index == index - 1:
                question = f"{self.lines[a.line_index].text} {question}"
            self.cancel(a.id)
        self._last_auto = now
        self._start(kind="auto", title="Answer", auto=True, line_index=index,
                    prompt=prompts.AUTO_PROMPT.format(question=question), screenshot=False)

    def _latest_auto(self) -> Answer | None:
        """An auto answer to the newest thing Them said, not yet shown by Ask."""
        last_them = next((i for i in range(len(self.lines) - 1, -1, -1)
                          if self.lines[i].source == "them"), None)
        for a in reversed(self.answers):
            if a.auto:
                if (a.line_index == last_them and not a.shown and not a.error
                        and not a.cancelled and time.time() - a.started < AUTO_FRESH_S):
                    return a
                return None
        return None

    async def ask(self, text: str | None = None, action: str = "assist",
                  screenshot: bool = True, monitor: str | None = None) -> None:
        if text:
            title, prompt, kind = text.strip()[:80], text.strip(), "ask"
        else:
            if action == "assist":
                ready = self._latest_auto()
                if ready:
                    ready.shown = True
                    self._emit({"ev": "answer.focus", "id": ready.id})
                    return
            title, prompt = prompts.ACTIONS.get(action, prompts.ACTIONS["assist"])
            kind = action
        for a in self.answers:
            if not a.auto and not a.done:
                self.cancel(a.id)
        a = self._start(kind=kind, title=title, prompt=prompt, screenshot=screenshot, monitor=monitor)
        a.shown = True

    def _start(self, *, kind: str, title: str, prompt: str, screenshot: bool,
               auto: bool = False, line_index: int | None = None, monitor: str | None = None) -> Answer:
        a = Answer(id=uuid.uuid4().hex[:8], kind=kind, title=title, auto=auto, line_index=line_index)
        self.answers.append(a)
        del self.answers[:-50]
        self._emit({"ev": "answer.start", **a.public(), "screenshot": screenshot})
        self._tasks[a.id] = asyncio.create_task(self._run(a, prompt, screenshot, monitor))
        return a

    async def _run(self, a: Answer, prompt: str, screenshot: bool, monitor: str | None) -> None:
        t0 = time.perf_counter()
        try:
            image = None
            if screenshot:
                try:
                    image = await capture(self.cfg.screenshot_scale, self.cfg.screenshot_quality, monitor)
                except Exception as e:
                    log.warning("screenshot failed, answering without it: %s", e)
                a.capture_ms = int((time.perf_counter() - t0) * 1000)
                self._emit({"ev": "answer.captured", "id": a.id, "capture_ms": a.capture_ms})
            req = Request(
                system=prompts.system_prompt(self.cfg.mode),
                context=prompts.context_block(self.cfg.context_text(), self.lines),
                prompt=prompt,
                image_jpeg=image,
            )
            async for delta in self.backend.stream(req):
                if a.first_ms is None:
                    a.first_ms = int((time.perf_counter() - t0) * 1000)
                a.text += delta
                self._emit({"ev": "answer.delta", "id": a.id, "text": delta})
            a.total_ms = int((time.perf_counter() - t0) * 1000)
            a.done = True
            self._emit({"ev": "answer.done", "id": a.id, "first_ms": a.first_ms, "total_ms": a.total_ms})
            log.info("%s answer: first token %s ms, done %s ms", a.kind, a.first_ms, a.total_ms)
        except asyncio.CancelledError:
            a.done = a.cancelled = True
            self._emit({"ev": "answer.done", "id": a.id, "cancelled": True})
            raise
        except BackendError as e:
            a.done, a.error = True, str(e)
            self._emit({"ev": "answer.done", "id": a.id, "error": a.error})
        except Exception as e:
            log.exception("answer failed")
            a.done, a.error = True, f"{type(e).__name__}: {e}"
            self._emit({"ev": "answer.done", "id": a.id, "error": a.error})
        finally:
            self._tasks.pop(a.id, None)

    def cancel(self, answer_id: str | None = None) -> None:
        ids = [answer_id] if answer_id else list(self._tasks)
        for i in ids:
            task = self._tasks.get(i)
            if task:
                task.cancel()

    # -- settings and state --------------------------------------------------

    def _apply_saved_state(self) -> None:
        try:
            saved = json.loads(STATE_FILE.read_text())
        except (OSError, ValueError):
            return
        for key, value in saved.items():
            if key in RUNTIME_KEYS:
                setattr(self.cfg, key, value)

    def _save_state(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({k: getattr(self.cfg, k) for k in sorted(RUNTIME_KEYS)}, indent=2))

    async def set(self, key: str, value) -> None:
        if key not in RUNTIME_KEYS:
            self._emit({"ev": "error", "message": f"unknown setting {key!r}"})
            return
        if getattr(self.cfg, key) == value:
            return
        setattr(self.cfg, key, value)
        self._save_state()
        if key in ("backend", "preset"):
            old = self.backend
            self.backend = make_backend(self.cfg)
            self._prime_backend()
            await self.backend.start()
            self._spawn(old.close())
        elif key == "mode":
            self._prime_backend()
        elif key in ("capture_mic", "capture_system") and self.listening:
            await self.listen(False)
            await self.listen(True)
        self._status()

    async def reset(self) -> None:
        self.cancel()
        self._save_session()
        self.lines.clear()
        self.answers.clear()
        self.partial = {"you": "", "them": ""}
        self.t0 = time.time()
        self._emit({"ev": "snapshot", **self.snapshot()})

    def _save_session(self) -> None:
        if not self.lines and not self.answers:
            return
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        name = datetime.fromtimestamp(self.t0).strftime("%Y-%m-%d_%H%M%S") + ".json"
        data = {"started": self.t0, "mode": self.cfg.mode,
                "lines": [asdict(ln) for ln in self.lines],
                "answers": [a.public() for a in self.answers if a.text]}
        (SESSIONS_DIR / name).write_text(json.dumps(data, indent=1))

    def status(self) -> dict:
        return {
            "listening": self.listening,
            "listen_started": self.listen_started,
            "stt_ready": self.stt is not None,
            "stt_error": self.stt_error,
            "backend": self.backend.describe(),
            "config": self.cfg.public(),
            "modes": {k: v[0] for k, v in prompts.MODES.items()},
            "actions": {k: v[0] for k, v in prompts.ACTIONS.items()},
        }

    def _status(self) -> None:
        self._emit({"ev": "status", **self.status()})

    def snapshot(self) -> dict:
        return {
            "status": self.status(),
            "t0": self.t0,
            "lines": [asdict(ln) for ln in self.lines[-300:]],
            "partial": self.partial,
            "answers": [a.public() for a in self.answers[-20:]],
        }

    # -- commands ------------------------------------------------------------

    async def handle(self, msg: dict) -> dict | None:
        """Run one command from a client. Returns a reply for that client only."""
        cmd = msg.get("cmd")
        if cmd in ("hello", "snapshot"):
            return {"ev": "snapshot", **self.snapshot()}
        if cmd == "listen":
            await self.listen(bool(msg.get("on", not self.listening)))
        elif cmd == "ask":
            await self.ask(text=msg.get("text"), action=msg.get("action", "assist"),
                           screenshot=bool(msg.get("screenshot", True)), monitor=msg.get("monitor"))
        elif cmd == "cancel":
            self.cancel(msg.get("id"))
        elif cmd == "reset":
            await self.reset()
        elif cmd == "set":
            await self.set(str(msg.get("key")), msg.get("value"))
        elif cmd == "ping":
            return {"ev": "pong", "t": msg.get("t")}
        else:
            return {"ev": "error", "message": f"unknown command {cmd!r}"}
        return None
