"""Measure streaming STT speed: per-chunk decode cost and real-time factor."""
import sys, time, wave
from pathlib import Path
import numpy as np
import sherpa_onnx

model_dir = Path(sys.argv[1]).expanduser()
threads = int(sys.argv[2]) if len(sys.argv) > 2 else 4

def load(wav):
    with wave.open(str(wav)) as w:
        assert w.getsampwidth() == 2
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        return a, w.getframerate()

t0 = time.perf_counter()
rec = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=str(model_dir / "tokens.txt"),
    encoder=str(model_dir / "encoder.int8.onnx"),
    decoder=str(model_dir / "decoder.int8.onnx"),
    joiner=str(model_dir / "joiner.int8.onnx"),
    num_threads=threads, sample_rate=16000, feature_dim=128,
    enable_endpoint_detection=True,
    rule2_min_trailing_silence=0.6,
)
print(f"load {time.perf_counter()-t0:.2f}s threads={threads}")

for wav in sorted((model_dir / "test_wavs").glob("[01].wav")):
    audio, sr = load(wav)
    s = rec.create_stream()
    chunk = int(0.16 * sr)
    costs = []
    for i in range(0, len(audio), chunk):
        s.accept_waveform(sr, audio[i:i + chunk])
        t = time.perf_counter()
        while rec.is_ready(s):
            rec.decode_stream(s)
        costs.append(time.perf_counter() - t)
    s.accept_waveform(sr, np.zeros(int(0.8 * sr), dtype=np.float32))
    s.input_finished()
    while rec.is_ready(s):
        rec.decode_stream(s)
    dur = len(audio) / sr
    c = np.array(costs) * 1000
    print(f"{wav.name}: {dur:.1f}s audio  RTF={c.sum()/1000/dur:.3f}  chunk p50={np.median(c):.1f}ms p95={np.percentile(c,95):.1f}ms")
    print("   ", rec.get_result(s))
print("ref:", (model_dir / "test_wavs/trans.txt").read_text().strip()[:300])
