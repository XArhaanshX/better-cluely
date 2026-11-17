"""Omnilingual ASR CTC decoding restricted to Devanagari.

Meta's Omnilingual ASR covers 1600 languages and takes no language hint.
Given a whole sentence of Hindi it writes Devanagari, but short utterances
carry too little context: on real speech, 4 of 9 utterances under 1.5 s
came out in Latin or Arabic script ("lakin", "هل" for "लेकिन", "हलो"). Casual
Hinglish is full of exactly those short bits (हाँ, अच्छा, अरे, नहीं ना).
sherpa-onnx can't restrict the output, so this runs the same ONNX model
directly and masks every token outside Devanagari before greedy CTC
decoding. English words spoken inside Hindi then come out in Devanagari,
which is how the model writes them in Hindi sentences anyway.

Masking alone empties a few very short utterances: with Latin gone, the
CTC blank outscores every Devanagari letter. When that happens the same
frames are decoded again with Latin allowed, so romanized Hindi such as
"lakin" (लेकिन) still shows; Arabic and every other script stay blocked.

Input handling follows sherpa-onnx's implementation: the whole utterance
is normalised to zero mean and unit variance. Token 0 (<s>) is the CTC
blank and token 4 is the word space.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import numpy as np

BLANK = 0
SPECIALS = (1, 2, 3)  # <pad>, </s>, <unk>: never output


def _letters(text: str) -> int:
    # Letters only: a stray "'" or a lone vowel sign doesn't count as text.
    return sum(c.isalpha() for c in text)


def _script(token: str) -> str:
    for ch in token:
        if ch.isalpha() or unicodedata.category(ch).startswith("M"):
            return unicodedata.name(ch, "").split(" ")[0]
    return ""  # digits, punctuation, space, specials


class OmniCtc:
    def __init__(self, model_dir: str | Path, threads: int = 4, restrict: bool = True):
        import onnxruntime as ort

        model_dir = Path(model_dir)
        self.tokens = [line.rstrip("\n").rsplit(" ", 1)[0]
                       for line in (model_dir / "tokens.txt").open(encoding="utf-8")]
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_dir / "model.int8.onnx"), opts,
                                            providers=["CPUExecutionProvider"])
        self.masks = []
        if restrict:
            self.masks = [self._mask(("DEVANAGARI",)), self._mask(("DEVANAGARI", "LATIN"))]

    def _mask(self, scripts: tuple[str, ...]) -> np.ndarray:
        keep = np.array([i == BLANK or _script(t) in ("",) + scripts
                         for i, t in enumerate(self.tokens)])
        keep[list(SPECIALS)] = False
        return np.where(keep, 0.0, -np.inf).astype(np.float32)

    def _greedy(self, logits: np.ndarray) -> str:
        out, prev = [], -1
        for i in logits.argmax(-1).tolist():
            if i != prev and i != BLANK:
                out.append(self.tokens[i])
            prev = i
        return " ".join("".join(out).split())

    def __call__(self, pcm: np.ndarray) -> str:
        if len(pcm) < 1600:  # under 0.1 s: nothing to read
            return ""
        x = ((pcm - pcm.mean()) / np.sqrt(pcm.var() + 1e-5)).astype(np.float32)[None, :]
        logits = self.session.run(None, {"x": x})[0][0]
        if not self.masks:
            return self._greedy(logits)
        devanagari, with_latin = self.masks
        text = self._greedy(logits + devanagari)
        if _letters(text):
            return text
        # Nothing in Devanagari: on short utterances the blank can just
        # outscore every Devanagari letter. Push it down a little and keep
        # that reading if it says about as much as the Latin one ("लो आ सर
        # र" over "alo asr re i"); otherwise the Latin reading ("lakin").
        latin = self._greedy(logits + with_latin)
        for penalty in (2.0, 3.0):
            pushed = logits + devanagari
            pushed[:, BLANK] -= penalty
            text = self._greedy(pushed)
            if _letters(text) and _letters(text) >= 0.5 * _letters(latin):
                return text
        return latin if _letters(latin) else ""
