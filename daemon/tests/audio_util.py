"""Load test audio as 16 kHz mono float32.

ffmpeg resamples with a proper low-pass filter. Plain interpolation from
22-48 kHz aliases, which can make the speech models hear almost nothing.
"""

import shutil
import subprocess

import numpy as np
import pytest


def load_16k(path) -> np.ndarray:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
