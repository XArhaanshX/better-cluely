import io

from PIL import Image

from wispd.screen import MAX_EDGE, _encode


def ppm(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (40, 80, 120)).save(buf, "PPM")
    return buf.getvalue()


def size(jpeg):
    return Image.open(io.BytesIO(jpeg)).size


def test_laptop_screen_uses_the_configured_scale():
    assert size(_encode(ppm(1920, 1200), 0.6, 70)) == (1152, 720)


def test_big_monitors_are_capped():
    w, h = size(_encode(ppm(3840, 2160), 0.6, 70))
    assert max(w, h) <= MAX_EDGE and abs(w / h - 16 / 9) < 0.01


def test_output_is_jpeg():
    assert _encode(ppm(800, 600), 0.6, 70)[:2] == b"\xff\xd8"
