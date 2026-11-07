"""Claude Code backend: answers through the user's `claude` CLI login.

Starting `claude -p` costs ~1.7 s before the first token. A process that
was started earlier and is waiting on stdin answers in ~0.85 s (Haiku), so
this backend keeps a small pool of idle processes ready. Each request takes
one, uses it once, and kills it; a replacement starts in the background.

One process per request keeps requests independent (no hidden conversation
building up), lets two run at once (an auto-answer and a manual ask), and
makes cancelling instant: kill the process.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from collections.abc import AsyncIterator

from ..config import DATA_DIR, Config
from .base import BackendError, Request

log = logging.getLogger(__name__)

WORK_DIR = DATA_DIR / "claude-code"


class ClaudeCodeBackend:
    name = "claude-code"

    def __init__(self, cfg: Config):
        self.model = cfg.resolved_model()
        self.effort = cfg.effort
        self.pool_size = max(1, cfg.pool_size)
        self._system = ""
        self._pool: list[asyncio.subprocess.Process] = []
        self._refill_task: asyncio.Task | None = None
        self._closed = False

    def describe(self) -> dict:
        return {"backend": self.name, "model": self.model, "effort": self.effort, "warm": len(self._pool)}

    async def start(self) -> None:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        self._kick_refill()

    # -- pool --------------------------------------------------------------

    def _cmd(self, system: str) -> list[str]:
        return [
            "claude", "-p",
            "--input-format", "stream-json", "--output-format", "stream-json",
            "--include-partial-messages", "--verbose",
            "--model", self.model,
            # Default effort lets the model think before open-ended prompts
            # like Assist: 3.8 s to first token instead of ~1.3 s.
            "--effort", self.effort,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
            "--system-prompt", system or "You are a helpful assistant.",
        ]

    async def _spawn(self, system: str) -> asyncio.subprocess.Process:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        proc = await asyncio.create_subprocess_exec(
            *self._cmd(system),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=WORK_DIR, env=env,
            limit=16 * 1024 * 1024,
        )
        proc.wisp_system = system  # type: ignore[attr-defined]
        return proc

    def _kick_refill(self) -> None:
        if self._closed or (self._refill_task and not self._refill_task.done()):
            return
        self._refill_task = asyncio.create_task(self._refill())

    async def _refill(self) -> None:
        try:
            while not self._closed and len(self._pool) < self.pool_size:
                self._pool.append(await self._spawn(self._system))
        except Exception:
            log.exception("could not start claude")

    def _take(self, system: str) -> asyncio.subprocess.Process | None:
        while self._pool:
            proc = self._pool.pop(0)
            if proc.returncode is None and getattr(proc, "wisp_system", None) == system:
                return proc
            _kill(proc)
        return None

    def set_system(self, system: str) -> None:
        """Change the system prompt; idle processes started with the old one are replaced."""
        if system == self._system:
            return
        self._system = system
        for proc in self._pool:
            _kill(proc)
        self._pool.clear()
        self._kick_refill()

    # -- requests ----------------------------------------------------------

    async def stream(self, req: Request) -> AsyncIterator[str]:
        self.set_system(req.system)
        proc = self._take(req.system) or await self._spawn(req.system)
        self._kick_refill()
        try:
            content: list[dict] = []
            if req.image_jpeg:
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg",
                    "data": base64.b64encode(req.image_jpeg).decode()}})
            text = f"{req.context}\n\n{req.prompt}" if req.context else req.prompt
            content.append({"type": "text", "text": text})
            msg = {"type": "user", "message": {"role": "user", "content": content}}
            assert proc.stdin and proc.stdout
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            await proc.stdin.drain()

            while True:
                line = await proc.stdout.readline()
                if not line:
                    err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
                    raise BackendError(f"claude exited: {err.strip()[:300] or 'no output'}")
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                kind = ev.get("type")
                if kind == "stream_event":
                    delta = ev.get("event", {}).get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield delta["text"]
                elif kind == "result":
                    if ev.get("is_error") or ev.get("subtype") != "success":
                        raise BackendError(str(ev.get("result") or ev.get("subtype")))
                    return
        finally:
            _kill(proc)

    async def close(self) -> None:
        self._closed = True
        for proc in self._pool:
            _kill(proc)
        self._pool.clear()


def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
