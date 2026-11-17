"""The Hindi decoder only ever writes Devanagari, or Latin as a fallback.
Skipped when the multilingual model isn't downloaded."""

import unicodedata

import numpy as np
import pytest

from tests.audio_util import load_16k as load
from wispd.config import DEFAULT_HI_MODEL

pytestmark = pytest.mark.skipif(not (DEFAULT_HI_MODEL / "model.int8.onnx").exists(),
                                reason="multilingual model not downloaded")


@pytest.fixture(scope="module")
def ctc():
    from wispd.omni import OmniCtc
    return OmniCtc(DEFAULT_HI_MODEL, 4)


def test_masks_allow_only_the_intended_scripts(ctc):
    from wispd.omni import BLANK, SPECIALS, _script
    devanagari, with_latin = ctc.masks
    for i, tok in enumerate(ctc.tokens):
        script = _script(tok)
        if i in SPECIALS:
            assert devanagari[i] == -np.inf and with_latin[i] == -np.inf
        elif i == BLANK or script == "":
            assert devanagari[i] == 0 and with_latin[i] == 0
        else:
            assert (devanagari[i] == 0) == (script == "DEVANAGARI")
            assert (with_latin[i] == 0) == (script in ("DEVANAGARI", "LATIN"))


@pytest.mark.parametrize("clip", ["en.wav", "de.wav", "es.wav", "fr.wav"])
def test_other_languages_never_leave_devanagari_or_latin(ctc, clip):
    pcm = load(DEFAULT_HI_MODEL / "test_wavs" / clip)
    for piece in (pcm, pcm[: 16000 // 2]):  # whole clip and a 0.5 s fragment
        text = ctc(piece)
        # Unicode script, so accented Latin ("país") counts as Latin.
        scripts = {unicodedata.name(c).split(" ")[0] for c in text if c.isalpha()}
        assert scripts <= {"DEVANAGARI", "LATIN"}, text


def test_too_short_is_empty(ctc):
    assert ctc(np.zeros(800, dtype=np.float32)) == ""


def test_a_full_english_sentence_in_hindi_mode_comes_out_as_english(ctc):
    """People switch to whole English sentences mid-call. The Devanagari
    pass finds no letters (once only a stray apostrophe), so the Latin
    fallback gives the English words."""
    from wispd.config import DEFAULT_STT_MODEL
    text = ctc(load(DEFAULT_STT_MODEL / "test_wavs" / "0.wav"))
    assert "nightfall" in text.lower() or "lamps" in text.lower(), text
