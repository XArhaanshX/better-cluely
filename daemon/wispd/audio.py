"""Audio capture from PipeWire through its PulseAudio interface (parec).

Two sources matter in a meeting: the microphone ("you") and the monitor of
the default output ("them": whatever the call app is playing). Both are read
as 16 kHz mono float32 in 20 ms frames, which is what the recognizer wants.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
FRAME_BYTES = FRAME_SAMPLES * 2  # s16le

DEVICES = {"you": "@DEFAULT_SOURCE@", "them": "@DEFAULT_MONITOR@"}


@dataclass
class Frame:
    source: str
    samples: np.ndarray  # float32 in [-1, 1]
    rms: float


class AudioCapture:
    """One parec process for one source. Restartable."""

    def __init__(self, source: str, device: str | None = None):
        self.source = source
        self.device = device or DEVICES[source]
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            "parec", "--raw", "--format=s16le", f"--rate={SAMPLE_RATE}", "--channels=1",
            "--latency-msec=20", f"--device={self.device}",
            "--client-name=wisp", f"--stream-name=wisp-{self.source}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        log.info("capturing %s from %s (pid %s)", self.source, self.device, self._proc.pid)

    async def frames(self) -> AsyncIterator[Frame]:
        assert self._proc and self._proc.stdout
        reader = self._proc.stdout
        while True:
            try:
                raw = await reader.readexactly(FRAME_BYTES)
            except asyncio.IncompleteReadError:
                err = b""
                if self._proc.stderr:
                    err = await self._proc.stderr.read()
                log.warning("%s capture ended: %s", self.source, err.decode(errors="replace").strip())
                return
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(pcm * pcm)))
            yield Frame(self.source, pcm, rms)

    async def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 2)
            except TimeoutError:
                proc.kill()
