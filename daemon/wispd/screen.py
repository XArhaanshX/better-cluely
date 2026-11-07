"""Screenshots for questions about what's on screen.

grim captures the focused monitor raw (PPM, ~35-45 ms at 1920x1200), and
Pillow scales and JPEG-encodes it (~27 ms). That beats grim's own
scaling (`grim -s 0.6 -t jpeg`, ~125 ms) by about 50 ms.

At 0.6x the image is ~1150x720 and ~70 KB, roughly 1.1k image tokens:
small enough to upload and read quickly, big enough to read code and
slide text.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging

from PIL import Image

log = logging.getLogger(__name__)


async def focused_monitor() -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "hyprctl", "monitors", "-j",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        for m in json.loads(out or b"[]"):
            if m.get("focused"):
                return m.get("name")
    except (OSError, ValueError) as e:
        log.debug("hyprctl monitors failed: %s", e)
    return None


# Longest edge sent to the model. The API scales bigger images down anyway,
# so anything above this is upload time and tokens for nothing (a 4K
# monitor at 0.6x would be 2304 px wide).
MAX_EDGE = 1568


def _encode(ppm: bytes, scale: float, quality: int, max_edge: int = MAX_EDGE) -> bytes:
    img = Image.open(io.BytesIO(ppm))
    w, h = img.size
    scale = min(scale, max_edge / max(w, h))
    if scale != 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.Resampling.BILINEAR, reducing_gap=2.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


async def capture(scale: float = 0.6, quality: int = 70, monitor: str | None = None) -> bytes:
    """JPEG of one monitor. Pass `monitor` when the caller knows it (saves ~11 ms)."""
    monitor = monitor or await focused_monitor()
    args = ["grim", "-t", "ppm"]
    if monitor:
        args += ["-o", monitor]
    args.append("-")
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"grim failed: {err.decode(errors='replace').strip()}")
    return await asyncio.to_thread(_encode, out, scale, quality)
