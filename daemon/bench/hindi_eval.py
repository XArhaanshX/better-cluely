"""Hindi recognition accuracy and speed on real recorded speech.

  uv run python bench/hindi_eval.py <clips-dir> [threads] [sherpa]

Uses wisp's decoder (omni.OmniCtc, kept to Devanagari) unless "sherpa" is
given, which runs plain sherpa-onnx for comparison.

<clips-dir> holds WAV files plus refs.json ({"name": {"text": ...}}), e.g.
clips from the IndicVoices-R Hindi set (unscripted speech, many speakers).
Prints character error rate (CER), word error rate (WER) and real-time
factor for the multilingual model wisp uses for Hindi.
"""

import json
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import sherpa_onnx

from wispd.config import DEFAULT_HI_MODEL as M
from wispd.omni import OmniCtc


def load(path: Path) -> np.ndarray:
    """16 kHz mono float32. ffmpeg resamples with a proper low-pass filter;
    plain interpolation from 48 kHz aliases, and on one clip that left the
    model hearing almost nothing (which looked like a model failure)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text.lower())
    # Chandrabindu and anusvara are written interchangeably in casual Hindi.
    text = text.replace("ँ", "ं")
    # Drop punctuation (incl. the danda) but keep vowel signs: Python's \w
    # does not match Devanagari combining marks, so a [^\w] filter would
    # strip every matra and score bare consonants.
    kept = "".join(" " if unicodedata.category(c)[0] in "PS" else c for c in text)
    return " ".join(kept.split())


def edits(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def main() -> None:
    clips = Path(sys.argv[1])
    threads = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    engine = sys.argv[3] if len(sys.argv) > 3 else "wisp"
    refs = json.loads((clips / "refs.json").read_text())
    if engine == "sherpa":
        rec = sherpa_onnx.OfflineRecognizer.from_omnilingual_asr_ctc(
            model=str(M / "model.int8.onnx"), tokens=str(M / "tokens.txt"), num_threads=threads)

        def decode(pcm):
            s = rec.create_stream()
            s.accept_waveform(16000, pcm)
            rec.decode_stream(s)
            return s.result.text
    else:
        decode = OmniCtc(M, threads)
    c_err = c_tot = w_err = w_tot = 0
    audio_s = compute_s = 0.0
    worst = []
    for name, ref in sorted(refs.items()):
        pcm = load(clips / f"{name}.wav")
        t = time.perf_counter()
        text = decode(pcm)
        compute_s += time.perf_counter() - t
        audio_s += len(pcm) / 16000
        hyp, gold = norm(text), norm(ref["text"])
        ce = edits(list(gold.replace(" ", "")), list(hyp.replace(" ", "")))
        we = edits(gold.split(), hyp.split())
        c_err += ce; c_tot += len(gold.replace(" ", ""))
        w_err += we; w_tot += len(gold.split())
        worst.append((ce / max(1, len(gold.replace(" ", ""))), name, gold, hyp))
    print(f"{len(refs)} clips, {audio_s:.0f} s of audio, {threads} threads, {engine}")
    print(f"CER {100 * c_err / c_tot:.1f}%   WER {100 * w_err / w_tot:.1f}%   "
          f"real-time factor {compute_s / audio_s:.3f}")
    worst.sort(reverse=True)
    for cer, name, gold, hyp in worst[:2] + worst[-1:]:
        print(f"\n{name} CER {100 * cer:.0f}%\n  ref: {gold}\n  hyp: {hyp}")


if __name__ == "__main__":
    main()
