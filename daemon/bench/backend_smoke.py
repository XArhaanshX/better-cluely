"""Smoke-test a backend: warm pool, time to first token, and cancellation."""
import asyncio, sys, time
from wispd.config import Config
from wispd.llm import Request, make_backend

async def main(backend: str):
    cfg = Config(backend=backend)
    b = make_backend(cfg)
    sys_prompt = "You are terse. Answer in one short sentence."
    if hasattr(b, "set_system"):
        b.set_system(sys_prompt)
    await b.start()
    await asyncio.sleep(6)
    print("describe:", b.describe())
    for q in ["Capital of Kenya?", "Largest planet?"]:
        t0 = time.perf_counter(); first = None; out = ""
        try:
            async for d in b.stream(Request(sys_prompt, "", q)):
                first = first or time.perf_counter() - t0; out += d
            print(f"ttft={first:.3f}s total={time.perf_counter()-t0:.3f}s {out.strip()!r}")
        except Exception as e:
            print("error:", type(e).__name__, e)
    # Cancellation: stop after the first token of a long answer.
    async def long():
        async for _ in b.stream(Request(sys_prompt, "", "Count from 1 to 300, one number per line.")):
            pass
    task = asyncio.create_task(long())
    await asyncio.sleep(1.5); t = time.perf_counter(); task.cancel()
    try: await task
    except asyncio.CancelledError: print(f"cancelled in {1000*(time.perf_counter()-t):.0f} ms")
    except Exception as e: print("cancel path error:", e)
    await b.close()

asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "claude-code"))
