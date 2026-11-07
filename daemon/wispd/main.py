"""wispd command line.

  wispd serve               run the daemon (what the systemd unit starts)
  wispd ask [TEXT]          ask through a running daemon and print the answer
  wispd listen on|off       start or stop listening
  wispd status              print the daemon's status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys

from . import config
from .server import Server
from .session import Session


async def serve() -> None:
    cfg = config.load()
    server = Server(config.SOCKET_PATH)
    session = Session(cfg, server.broadcast)
    await session.start()
    await server.start(session)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    logging.info("shutting down")
    await server.close()
    await session.close()


async def client(cmd: dict, follow_answer: bool) -> int:
    try:
        reader, writer = await asyncio.open_unix_connection(str(config.SOCKET_PATH))
    except OSError:
        print(f"wispd is not running ({config.SOCKET_PATH})", file=sys.stderr)
        return 1
    writer.write((json.dumps({"cmd": "hello"}) + "\n").encode())
    hello = json.loads(await reader.readline())
    if not follow_answer:
        if cmd["cmd"] == "status":
            print(json.dumps(hello["status"], indent=2))
        else:
            writer.write((json.dumps(cmd) + "\n").encode())
            await writer.drain()
        writer.close()
        return 0
    writer.write((json.dumps(cmd) + "\n").encode())
    await writer.drain()
    answer_id = None
    while line := await reader.readline():
        ev = json.loads(line)
        kind = ev.get("ev")
        if kind == "answer.start" and not ev.get("auto") and answer_id is None:
            answer_id = ev["id"]
        elif kind == "answer.focus" and answer_id is None:
            answer_id = ev["id"]
            text = next((a["text"] for a in hello["answers"] if a["id"] == answer_id), "")
            print(text, end="", flush=True)
        elif kind == "answer.delta" and ev.get("id") == answer_id:
            print(ev["text"], end="", flush=True)
        elif kind == "answer.done" and ev.get("id") == answer_id:
            print()
            if ev.get("error"):
                print(f"error: {ev['error']}", file=sys.stderr)
                return 1
            print(f"[first token {ev.get('first_ms')} ms, done {ev.get('total_ms')} ms]", file=sys.stderr)
            return 0
        elif kind == "error":
            print(f"error: {ev.get('message')}", file=sys.stderr)
    return 1


def main() -> None:
    p = argparse.ArgumentParser(prog="wispd")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    ask = sub.add_parser("ask")
    ask.add_argument("text", nargs="*")
    ask.add_argument("--action", default="assist")
    ask.add_argument("--no-screenshot", action="store_true")
    listen = sub.add_parser("listen")
    listen.add_argument("state", choices=["on", "off"])
    sub.add_parser("status")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "serve":
        asyncio.run(serve())
        return
    if args.command == "ask":
        cmd = {"cmd": "ask", "action": args.action, "screenshot": not args.no_screenshot}
        if args.text:
            cmd["text"] = " ".join(args.text)
        sys.exit(asyncio.run(client(cmd, follow_answer=True)))
    if args.command == "listen":
        sys.exit(asyncio.run(client({"cmd": "listen", "on": args.state == "on"}, False)))
    if args.command == "status":
        sys.exit(asyncio.run(client({"cmd": "status"}, False)))


if __name__ == "__main__":
    main()
