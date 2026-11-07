"""Streaming speech-to-text for both sides of the conversation.

One sherpa-onnx recognizer serves both sources ("you" and "them") from a
single worker thread, decoding whichever streams are ready in one batch.

Silence is not decoded. A per-source level gate opens when audio rises above
a threshold, replays a short pre-roll so the first syllable isn't clipped,
and stays open long enough after speech ends for the endpoint detector to
close the utterance. That keeps CPU use near zero when nobody is talking.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio import FRAME_MS, SAMPLE_RATE

log = logging.getLogger(__name__)

PREROLL_FRAMES = 200 // FRAME_MS
# Must outlast rule2_min_trailing_silence so the endpoint fires while fed.
HANGOVER_FRAMES = 1300 // FRAME_MS
ENDPOINT_SILENCE_S = 0.8
# Queue items handled between decodes: about one 160 ms model chunk per
# source. Draining more at once lets a backlog run past an endpoint, so
# the next utterance gets glued onto the previous one.
MAX_ITEMS_PER_PASS = 2 * 160 // FRAME_MS


@dataclass
class Utterance:
    source: str
    text: str
    started: float
    ended: float
    final: bool


@dataclass
class _SourceState:
    stream: object
    gate: float
    preroll: collections.deque = field(default_factory=lambda: collections.deque(maxlen=PREROLL_FRAMES))
    hang: int = 0
    started: float = 0.0
    last_text: str = ""


class Transcriber:
    def __init__(self, model_dir: str | Path, threads: int,
                 emit: Callable[[Utterance], None], loop: asyncio.AbstractEventLoop):
        self.model_dir = Path(model_dir).expanduser()
        self.threads = threads
        self._emit = emit
        self._loop = loop
        self._rec = None
        self._q: queue.Queue = queue.Queue()
        self._sources: dict[str, _SourceState] = {}
        self._thread: threading.Thread | None = None
        self._running = False

    # -- setup -------------------------------------------------------------

    def load(self) -> None:
        """Blocking model load (~2.5 s). Run it in an executor."""
        import sherpa_onnx

        d = self.model_dir
        t = time.perf_counter()
        self._rec = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(d / "tokens.txt"),
            encoder=str(d / "encoder.int8.onnx"),
            decoder=str(d / "decoder.int8.onnx"),
            joiner=str(d / "joiner.int8.onnx"),
            num_threads=self.threads,
            sample_rate=SAMPLE_RATE,
            feature_dim=128,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=ENDPOINT_SILENCE_S,
            rule3_min_utterance_length=20.0,
        )
        log.info("STT model loaded in %.1fs from %s", time.perf_counter() - t, d.name)

    @property
    def loaded(self) -> bool:
        return self._rec is not None

    def add_source(self, name: str, gate: float) -> None:
        self._q.put(("add", name, gate))

    def start(self) -> None:
        assert self._rec is not None, "call load() first"
        self._running = True
        self._thread = threading.Thread(target=self._run, name="wisp-stt", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    # -- input (called from the asyncio thread) ----------------------------

    def push(self, source: str, samples: np.ndarray, rms: float) -> None:
        self._q.put(("audio", source, samples, rms))

    def flush(self, source: str) -> None:
        """Force the current utterance of a source to finish now."""
        self._q.put(("flush", source))

    # -- worker ------------------------------------------------------------

    def _run(self) -> None:
        rec = self._rec
        while self._running:
            try:
                items = [self._q.get(timeout=0.05)]
            except queue.Empty:
                continue
            while len(items) < MAX_ITEMS_PER_PASS:
                try:
                    items.append(self._q.get_nowait())
                except queue.Empty:
                    break

            for item in items:
                kind = item[0]
                if kind == "add":
                    _, name, gate = item
                    if name not in self._sources:
                        self._sources[name] = _SourceState(rec.create_stream(), gate)
                elif kind == "audio":
                    self._feed(*item[1:])
                elif kind == "flush":
                    st = self._sources.get(item[1])
                    if st:
                        self._finish(item[1], st)

            ready = [st.stream for st in self._sources.values() if rec.is_ready(st.stream)]
            while ready:
                rec.decode_streams(ready)
                ready = [s for s in ready if rec.is_ready(s)]

            for name, st in self._sources.items():
                text = rec.get_result(st.stream).strip()
                if text != st.last_text:
                    st.last_text = text
                    self._send(Utterance(name, text, st.started, time.time(), final=False))
                if rec.is_endpoint(st.stream):
                    self._finish(name, st)

    def _feed(self, source: str, samples: np.ndarray, rms: float) -> None:
        st = self._sources.get(source)
        if st is None:
            return
        if rms >= st.gate:
            if st.hang == 0:
                # Gate opening: replay what came just before.
                if not st.last_text:
                    st.started = time.time() - len(st.preroll) * FRAME_MS / 1000
                for f in st.preroll:
                    st.stream.accept_waveform(SAMPLE_RATE, f)
                st.preroll.clear()
            st.hang = HANGOVER_FRAMES
            st.stream.accept_waveform(SAMPLE_RATE, samples)
        elif st.hang > 0:
            st.hang -= 1
            st.stream.accept_waveform(SAMPLE_RATE, samples)
        else:
            st.preroll.append(samples)

    def _finish(self, name: str, st: _SourceState) -> None:
        text = self._rec.get_result(st.stream).strip()
        if text:
            self._send(Utterance(name, text, st.started, time.time(), final=True))
        self._rec.reset(st.stream)
        st.last_text = ""

    def _send(self, u: Utterance) -> None:
        self._loop.call_soon_threadsafe(self._emit, u)
