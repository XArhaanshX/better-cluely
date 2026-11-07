"""Acoustic echo cancellation for the mic when the output is loudspeakers.

On laptop or monitor speakers the mic hears the other side of the call, so
their words would also be transcribed as "You". This runs PipeWire's own
echo-cancel module (WebRTC AEC) as a small private PipeWire client:

  mic ────────────────► wisp_aec_capture ─┐
                                          ├─ WebRTC AEC ─► wisp_aec_source
  default output monitor ► wisp_aec_ref ──┘   (what wisp records as "You")

`monitor.mode` takes the echo reference from the monitor of the default
output, so the call app's audio is not rerouted and nothing else on the
system changes: no default device moves (the new source has the lowest
priority), and the whole thing disappears when the process exits. It runs
only while listening on loudspeakers; the daemon's systemd cgroup cleans it
up if the daemon dies.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

log = logging.getLogger(__name__)

SOURCE_NAME = "wisp_aec_source"


def config_text(source_name: str = SOURCE_NAME, mic: str | None = None,
                output: str | None = None, mic_is_sink: bool = False) -> str:
    """PipeWire client config. `mic` and `output` pin the devices (tests use
    virtual ones); left out, it follows the default mic and default output.
    PipeWire has no ".monitor" source names: to use a sink's monitor as the
    mic, name the sink and set `mic_is_sink`."""
    prefix = source_name.removesuffix("_source")
    capture_target = f'target.object = "{mic}"' if mic else ""
    if mic and mic_is_sink:
        capture_target += " stream.capture.sink = true"
    ref_target = f'target.object = "{output}"' if output else ""
    return f"""
context.properties = {{ log.level = 1 }}
context.spa-libs = {{
    audio.convert.* = audioconvert/libspa-audioconvert
    support.*       = support/libspa-support
}}
context.modules = [
    {{ name = libpipewire-module-rt args = {{ }} flags = [ ifexists nofail ] }}
    {{ name = libpipewire-module-protocol-native }}
    {{ name = libpipewire-module-client-node }}
    {{ name = libpipewire-module-adapter }}
    {{ name = libpipewire-module-echo-cancel
        args = {{
            library.name = aec/libspa-aec-webrtc
            # Echo cancellation only. The noise suppressor, gain control and
            # transient suppressor reshape speech, and the speech recognizer
            # does best on unprocessed audio.
            aec.args = {{
                webrtc.gain_control = false
                webrtc.noise_suppression = false
                webrtc.transient_suppression = false
                webrtc.voice_detection = false
                webrtc.high_pass_filter = true
            }}
            monitor.mode = true
            capture.props = {{ node.name = "{prefix}_capture" {capture_target} }}
            sink.props    = {{ node.name = "{prefix}_ref" {ref_target} }}
            source.props  = {{
                node.name = "{source_name}"
                node.description = "wisp echo-cancelled mic"
                priority.session = 1
                priority.driver = 1
            }}
        }}
    }}
]
"""


async def _source_exists(name: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "pactl", "list", "short", "sources",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    return any(line.split("\t")[1:2] == [name] for line in out.decode().splitlines())


class EchoCanceller:
    def __init__(self, conf_dir: Path, source_name: str = SOURCE_NAME,
                 mic: str | None = None, output: str | None = None, mic_is_sink: bool = False):
        self.conf_path = conf_dir / f"{source_name}.conf"
        self.source_name = source_name
        self._mic = mic
        self._output = output
        self._mic_is_sink = mic_is_sink
        self._proc: asyncio.subprocess.Process | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self, timeout: float = 3.0) -> bool:
        """Start it and wait for the cleaned source. False means: not available,
        carry on without it."""
        if self.running:
            return True
        try:
            self.conf_path.parent.mkdir(parents=True, exist_ok=True)
            self.conf_path.write_text(config_text(self.source_name, self._mic, self._output, self._mic_is_sink))
            self._proc = await asyncio.create_subprocess_exec(
                "pipewire", "-c", str(self.conf_path),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        except OSError as e:
            log.warning("echo cancellation unavailable: %s", e)
            self._proc = None
            return False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self._proc.returncode is not None:
                err = (await self._proc.stderr.read()).decode(errors="replace").strip() if self._proc.stderr else ""
                log.warning("echo cancellation exited: %s", err[-300:] or self._proc.returncode)
                self._proc = None
                return False
            if await _source_exists(self.source_name):
                log.info("echo cancellation on (%s)", self.source_name)
                return True
            await asyncio.sleep(0.1)
        log.warning("echo cancellation did not come up in %.1fs", timeout)
        await self.stop()
        return False

    async def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 2)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            log.info("echo cancellation off")
