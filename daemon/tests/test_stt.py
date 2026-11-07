"""Integration test: the transcriber turns two clips separated by silence into
two final utterances, in real time order. Skipped when the model is missing."""

import asyncio
import wave
from pathlib import Path

import numpy as np
import pytest

from wispd.audio import FRAME_SAMPLES
from wispd.config import DEFAULT_STT_MODEL
from wispd.stt import Transcriber

WAVS = DEFAULT_STT_MODEL / "test_wavs"
pytestmark = pytest.mark.skipif(not WAVS.exists(), reason="STT model not downloaded")


def frames(path: Path):
    with wave.open(str(path)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    for i in range(0, len(pcm) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
        yield pcm[i:i + FRAME_SAMPLES]


def test_two_clips_two_utterances():
    async def run():
        loop = asyncio.get_running_loop()
        got = []
        t = Transcriber(DEFAULT_STT_MODEL, 2, got.append, loop)
        await loop.run_in_executor(None, t.load)
        t.add_source("them", 0.001)
        t.start()
        silence = np.zeros(FRAME_SAMPLES, dtype=np.float32)
        for clip in ("0.wav", "1.wav"):
            for f in frames(WAVS / clip):
                t.push("them", f, float(np.sqrt(np.mean(f * f))))
                await asyncio.sleep(0.004)  # ~5x real time
            for _ in range(100):  # 2 s of digital silence
                t.push("them", silence, 0.0)
                await asyncio.sleep(0.004)
        # Decoding runs at ~0.6x real time, so let the backlog drain.
        for _ in range(600):
            if sum(u.final for u in got) >= 2:
                break
            await asyncio.sleep(0.1)
        t.stop()
        return [u for u in got if u.final]

    finals = asyncio.run(run())
    assert len(finals) == 2, [u.text for u in finals]
    assert finals[0].text.lower().startswith("after early nightfall")
    assert "lovely child" in finals[1].text.lower()
    assert finals[0].ended <= finals[1].started
