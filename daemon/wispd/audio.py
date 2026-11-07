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


async def _pactl(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "pactl", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    return out.decode().strip()


async def default_devices() -> tuple[str, str]:
    """(default sink, default source) names."""
    sink, source = await asyncio.gather(_pactl("get-default-sink"), _pactl("get-default-source"))
    return sink, source


def echo_risk(sink: str) -> bool:
    """True when the output is loudspeakers the mic can hear.

    Headphones, headsets and Bluetooth audio don't leak into the mic.
    Laptop speakers and HDMI monitors do.
    """
    s = sink.lower()
    return not ("headphone" in s or "headset" in s or s.startswith("bluez_output"))


class DeviceWatcher:
    """Calls `on_change(sink, source)` when the default sink or source changes.

    Follows `pactl subscribe` and re-reads the defaults on server events, so
    plugging in or disconnecting headphones mid-call moves the capture to
    the new device instead of listening to a dead one.
    """

    def __init__(self, on_change):
        self._on_change = on_change
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None
        self.sink = ""
        self.source = ""

    async def start(self) -> None:
        self.sink, self.source = await default_devices()
        self._proc = await asyncio.create_subprocess_exec(
            "pactl", "subscribe", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        assert self._proc and self._proc.stdout
        while line := await self._proc.stdout.readline():
            if b"on server" not in line:
                continue
            sink, source = await default_devices()
            if (sink, source) != (self.sink, self.source):
                old = (self.sink, self.source)
                self.sink, self.source = sink, source
                log.info("default devices changed: %s -> %s", old, (sink, source))
                await self._on_change(sink, source, old)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
