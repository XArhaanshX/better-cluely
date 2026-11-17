"""Hindi recognition accuracy and speed on real recorded speech.

  uv run python bench/hindi_eval.py <clips-dir> [threads]

<clips-dir> holds WAV files plus refs.json ({"name": {"text": ...}}), e.g.
clips from the IndicVoices-R Hindi set (unscripted speech, many speakers).
Prints character error rate (CER), word error rate (WER) and real-time
factor for the multilingual model wisp uses for Hindi.
"""

import json
import sys
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx

from wispd.config import DEFAULT_HI_MODEL as M


def load(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        ch, rate = w.getnchannels(), w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    pcm = pcm.reshape(-1, ch).mean(axis=1)
    if rate != 16000:
        idx = np.arange(0, len(pcm), rate / 16000)
        pcm = np.interp(idx, np.arange(len(pcm)), pcm).astype(np.float32)
    return pcm


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
    refs = json.loads((clips / "refs.json").read_text())
    rec = sherpa_onnx.OfflineRecognizer.from_omnilingual_asr_ctc(
        model=str(M / "model.int8.onnx"), tokens=str(M / "tokens.txt"), num_threads=threads)
    c_err = c_tot = w_err = w_tot = 0
    audio_s = compute_s = 0.0
    worst = []
    for name, ref in sorted(refs.items()):
        pcm = load(clips / f"{name}.wav")
        t = time.perf_counter()
        s = rec.create_stream()
        s.accept_waveform(16000, pcm)
        rec.decode_stream(s)
        compute_s += time.perf_counter() - t
        audio_s += len(pcm) / 16000
        hyp, gold = norm(s.result.text), norm(ref["text"])
        ce = edits(list(gold.replace(" ", "")), list(hyp.replace(" ", "")))
        we = edits(gold.split(), hyp.split())
        c_err += ce; c_tot += len(gold.replace(" ", ""))
        w_err += we; w_tot += len(gold.split())
        worst.append((ce / max(1, len(gold.replace(" ", ""))), name, gold, hyp))
    print(f"{len(refs)} clips, {audio_s:.0f} s of audio, {threads} threads")
    print(f"CER {100 * c_err / c_tot:.1f}%   WER {100 * w_err / w_tot:.1f}%   "
          f"real-time factor {compute_s / audio_s:.3f}")
    worst.sort(reverse=True)
    for cer, name, gold, hyp in worst[:2] + worst[-1:]:
        print(f"\n{name} CER {100 * cer:.0f}%\n  ref: {gold}\n  hyp: {hyp}")


if __name__ == "__main__":
    main()
