"""Measure the echo canceller on virtual devices only; nothing plays aloud.

A fake room:
  far end  : clip 1 plays into null sink "wisp_t_spk"   (the speakers)
  echo path: loopback wisp_t_spk.monitor -> null sink "wisp_t_room"
  near end : clip 0 plays into "wisp_t_room" from t=9 s (you, talking over them)
  mic      : wisp_t_room.monitor  (hears the speakers and you)

wisp's EchoCanceller is pointed at that mic and those speakers, exactly as
in production except for the device names. Both the raw mic and the
cleaned source are recorded, then transcribed with the production model.
"""

import asyncio
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx

from wispd.aec import EchoCanceller
from wispd.config import DEFAULT_STT_MODEL as M

FAR, NEAR = M / "test_wavs/1.wav", M / "test_wavs/0.wav"
NEAR_AT = float(sys.argv[1]) if len(sys.argv) > 1 else 9.0
DURATION = NEAR_AT + 10.0
FAR_WORDS = {"god", "consequence", "punished", "lovely", "child", "bosom", "mortals", "heaven", "dishonoured", "dishonored"}
NEAR_WORDS = {"nightfall", "yellow", "lamps", "light", "squalid", "quarter", "brothels"}


def pactl(*a):
    return subprocess.run(["pactl", *a], capture_output=True, text=True).stdout.strip()


def transcribe(pcm: np.ndarray) -> str:
    rec = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(M / "tokens.txt"), encoder=str(M / "encoder.int8.onnx"),
        decoder=str(M / "decoder.int8.onnx"), joiner=str(M / "joiner.int8.onnx"),
        num_threads=2, feature_dim=128)
    s = rec.create_stream()
    s.accept_waveform(16000, pcm)
    s.accept_waveform(16000, np.zeros(16000, dtype=np.float32))
    s.input_finished()
    while rec.is_ready(s):
        rec.decode_stream(s)
    return rec.get_result(s)


def score(text: str) -> tuple[int, int]:
    words = {w.strip(".,?!").lower() for w in text.split()}
    return len(words & NEAR_WORDS), len(words & FAR_WORDS)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x * x))) + 1e-9


async def record(device: str, path: Path) -> asyncio.subprocess.Process:
    f = path.open("wb")
    return await asyncio.create_subprocess_exec(
        "parec", "--raw", "--format=s16le", "--rate=16000", "--channels=1",
        "--latency-msec=20", f"--device={device}", stdout=f)


async def main() -> int:
    mods = [
        pactl("load-module", "module-null-sink", "sink_name=wisp_t_spk", "sink_properties=node.group=wisp_t_clock"),
        pactl("load-module", "module-null-sink", "sink_name=wisp_t_room", "sink_properties=node.group=wisp_t_clock"),
    ]
    mods.append(pactl("load-module", "module-loopback", "source=wisp_t_spk.monitor",
                      "sink=wisp_t_room", "latency_msec=40"))
    tmp = Path(tempfile.mkdtemp(prefix="wisp-aec-"))
    aec = EchoCanceller(tmp, source_name="wisp_t_aec_source",
                        mic="wisp_t_room", output="wisp_t_spk", mic_is_sink=True)
    try:
        if not await aec.start():
            print("echo canceller failed to start")
            return 1
        raw_p = await record("wisp_t_room.monitor", tmp / "raw.pcm")
        clean_p = await record("wisp_t_aec_source", tmp / "clean.pcm")
        await asyncio.sleep(0.5)
        far = await asyncio.create_subprocess_exec("paplay", "-d", "wisp_t_spk", str(FAR))
        await asyncio.sleep(NEAR_AT)
        near = await asyncio.create_subprocess_exec("paplay", "-d", "wisp_t_room", str(NEAR))
        await asyncio.sleep(DURATION - NEAR_AT)
        await far.wait()
        await near.wait()
        for p in (raw_p, clean_p):
            p.terminate()
            await p.wait()
    finally:
        await aec.stop()
        for m in reversed(mods):
            if m:
                pactl("unload-module", m)

    load = lambda n: np.frombuffer((tmp / n).read_bytes(), dtype=np.int16).astype(np.float32) / 32768
    raw, clean = load("raw.pcm"), load("clean.pcm")
    n = min(len(raw), len(clean))
    raw, clean = raw[:n], clean[:n]
    # Far end only, after the canceller has had 3 s to converge.
    a, b = int(3.5 * 16000), int((NEAR_AT + 0.3) * 16000)
    erle = 20 * np.log10(rms(raw[a:b]) / rms(clean[a:b]))
    print(f"recorded {n / 16000:.1f} s")
    # Integrity: dropouts (runs of exact zeros) and resemblance to your clip.
    def zero_runs(x):
        z = (x == 0).astype(np.int8)
        edges = np.diff(np.concatenate([[0], z, [0]]))
        lengths = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
        return int((lengths > 160).sum())
    with wave.open(str(NEAR)) as w:
        ref = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    def best_corr(x):
        seg = x[int(NEAR_AT * 16000): int((NEAR_AT + 7.5) * 16000)]
        c = np.correlate(seg, ref[: 4 * 16000], mode="valid")
        return float(c.max() / (np.linalg.norm(ref[: 4 * 16000]) * np.sqrt(np.convolve(seg * seg, np.ones(4 * 16000), "valid").max()) + 1e-9)), int(c.argmax())
    for name, x in (("raw", raw), ("clean", clean)):
        corr, lag = best_corr(x)
        print(f"{name:5s}: dropouts>10ms={zero_runs(x)}, match to your clip={corr:.2f} at +{lag / 16000:.2f}s")
    print(f"echo reduction while only the far end talks: {erle:.1f} dB")
    c, d = int((NEAR_AT + 0.5) * 16000), int((NEAR_AT + 6.0) * 16000)
    print(f"level while you talk: raw {rms(raw[c:d]):.4f}, cleaned {rms(clean[c:d]):.4f}")
    for name, pcm in (("raw mic", raw), ("cleaned", clean)):
        text = transcribe(pcm)
        near_hits, far_hits = score(text)
        print(f"{name:8s}: your words {near_hits}/{len(NEAR_WORDS)}, their words {far_hits}/{len(FAR_WORDS)}")
        print(f"          {text[:160]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
