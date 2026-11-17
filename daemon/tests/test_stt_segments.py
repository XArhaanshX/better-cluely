"""Integration test for the utterance-based transcriber used for Hindi.
Uses the recordings bundled with the multilingual model; skipped when the
model is not downloaded."""

import asyncio

import numpy as np
import pytest

from tests.audio_util import load_16k
from wispd.audio import FRAME_SAMPLES
from wispd.config import DEFAULT_HI_MODEL, VAD_MODEL
from wispd.stt_segments import SegmentTranscriber

WAVS = DEFAULT_HI_MODEL / "test_wavs"
pytestmark = pytest.mark.skipif(not (WAVS.exists() and VAD_MODEL.exists()),
                                reason="multilingual model or VAD not downloaded")


def frames(path):
    pcm = load_16k(path)
    for i in range(0, len(pcm) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
        yield pcm[i:i + FRAME_SAMPLES]


def test_two_clips_two_lines_with_live_partials():
    async def run():
        loop = asyncio.get_running_loop()
        got = []
        t = SegmentTranscriber(DEFAULT_HI_MODEL, VAD_MODEL, 4, got.append, loop)
        await loop.run_in_executor(None, t.load)
        t.add_source("them", 0.0)
        t.start()
        silence = np.zeros(FRAME_SAMPLES, dtype=np.float32)
        for clip in ("en.wav", "fr.wav"):
            for f in frames(WAVS / clip):
                t.push("them", f, float(np.sqrt(np.mean(f * f))) or 1e-6)
                await asyncio.sleep(0.005)
            for _ in range(75):  # 1.5 s of silence ends the utterance
                t.push("them", silence, 0.0)
                await asyncio.sleep(0.005)
        for _ in range(300):
            if sum(u.final for u in got) >= 2:
                break
            await asyncio.sleep(0.1)
        t.stop()
        return got

    got = asyncio.run(run())
    finals = [u for u in got if u.final]
    partials = [u for u in got if not u.final]
    assert len(finals) == 2, [u.text for u in finals]
    assert all(u.text for u in finals)
    assert finals[0].ended <= finals[1].ended
    # Captions appeared while the first clip was still being spoken.
    assert partials and partials[0].ended < finals[0].ended
