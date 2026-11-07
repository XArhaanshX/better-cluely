"""Measure Claude Code first-token latency: pre-spawned idle process vs warm session.

Also checks that stream-json input accepts an image content block.
"""
import base64, json, os, subprocess, sys, tempfile, time

MODEL = sys.argv[1] if len(sys.argv) > 1 else "haiku"
CMD = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json",
       "--include-partial-messages", "--verbose", "--model", MODEL, "--tools", "",
       "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
       "--system-prompt", "You are a terse assistant. Answer in one short sentence."]

def spawn():
    return subprocess.Popen(CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, bufsize=1, cwd=tempfile.gettempdir())

def ask(p, content):
    t0 = time.perf_counter()
    p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n")
    p.stdin.flush()
    first, text = None, ""
    for line in p.stdout:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "stream_event":
            d = ev["event"].get("delta", {})
            if d.get("type") == "text_delta":
                first = first or time.perf_counter() - t0
                text += d["text"]
        elif ev.get("type") == "result":
            return first, text.strip()[:70]
    return None, "EOF"

p = spawn()
time.sleep(6)  # let it finish booting, as a pre-warmed pool process would
print("pre-spawned first msg: ttft=%.3fs %r" % ask(p, "Capital of France?"))
print("same process, 2nd msg: ttft=%.3fs %r" % ask(p, "And of Japan?"))
shot = subprocess.run(["grim", "-t", "jpeg", "-q", "70", "-s", "0.6", "-"], capture_output=True).stdout
img = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                    "data": base64.b64encode(shot).decode()}}
print("image (%d KB): ttft=%.3fs %r" % ((len(shot) // 1024,) + ask(p, [img, {"type": "text", "text": "In 8 words, what app is on screen?"}])))
p.stdin.close(); p.wait(timeout=10)
