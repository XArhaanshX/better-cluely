"""End-to-end listening check without touching real speakers.

Creates a temporary null sink, points the 'them' capture at its monitor,
plays a test clip into it, and prints what the session transcribed.

  uv run python bench/listen_e2e.py                    # English test clip
  uv run python bench/listen_e2e.py CLIP.wav hi        # any clip, Hindi model
"""
import asyncio, subprocess, sys, time
from wispd import audio, config
from wispd.session import Session

async def main():
    mod = subprocess.run(["pactl", "load-module", "module-null-sink", "sink_name=wisp_test",
                          "sink_properties=device.description=wisp-test"], capture_output=True, text=True).stdout.strip()
    audio.DEVICES["them"] = "wisp_test.monitor"
    events = []
    _append = events.append
    def stamp(e):
        e["_t"] = time.time(); _append(e)
    wav = sys.argv[1] if len(sys.argv) > 1 else str(config.DEFAULT_STT_MODEL / "test_wavs" / "0.wav")
    language = sys.argv[2] if len(sys.argv) > 2 else "en"
    cfg = config.Config(capture_mic=False, auto_answer=False, auto_notes=False, language=language)
    s = Session(cfg, stamp)
    try:
        await s.start()
        while s.stt is None:
            await asyncio.sleep(0.1)
        await s.listen(True)
        await asyncio.sleep(1)
        t0 = time.time()
        # Must not block the event loop, or parec's output piles up unread.
        play = await asyncio.create_subprocess_exec("paplay", "-d", "wisp_test", wav)
        await play.wait()
        t_end = time.time()
        while not s.lines and time.time() - t_end < 8:
            await asyncio.sleep(0.05)
        partials = [e for e in events if e["ev"] == "partial"]
        first_partial = next((e for e in partials if e["text"]), None)
        print(f"language {language}; clip {t_end - t0:.1f}s; partial updates: {len(partials)}"
              + (f"; first caption {first_partial['_t'] - t0:.2f}s after the clip started" if first_partial else ""))
        if s.lines:
            print(f"final {time.time() - t_end:.2f}s after the clip ended: {s.lines[0].text!r}")
        else:
            print("no final line")
        for e in partials[-4:]:
            print(f"  partial at {e['_t'] - t_end:+.2f}s: ...{e['text'][-40:]!r}")
        print("level events:", sum(e['ev'] == 'level' for e in events))
    finally:
        await s.close()
        subprocess.run(["pactl", "unload-module", mod])

asyncio.run(main())
