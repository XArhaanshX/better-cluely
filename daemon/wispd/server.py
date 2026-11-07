"""Unix socket server: newline-delimited JSON in both directions.

Clients (the Quickshell UI, `wispd ask`) send commands like
{"cmd": "ask", "action": "assist"} and receive every event the session
emits. A slow client never blocks the others: each has its own bounded
queue, and a client that falls too far behind is dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path

from .session import Session

log = logging.getLogger(__name__)
QUEUE_LIMIT = 2000


class Client:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(QUEUE_LIMIT)
        self.writer_task: asyncio.Task | None = None

    def send(self, data: bytes) -> bool:
        try:
            self.queue.put_nowait(data)
            return True
        except asyncio.QueueFull:
            return False

    async def write_loop(self) -> None:
        while True:
            data = await self.queue.get()
            self.writer.write(data)
            await self.writer.drain()


class Server:
    def __init__(self, socket_path: Path):
        self.socket_path = socket_path
        self.clients: set[Client] = set()
        self.session: Session | None = None
        self._server: asyncio.base_events.Server | None = None

    def broadcast(self, event: dict) -> None:
        data = (json.dumps(event, separators=(",", ":")) + "\n").encode()
        for client in list(self.clients):
            if not client.send(data):
                log.warning("dropping a client that stopped reading")
                self._drop(client)

    def _drop(self, client: Client) -> None:
        self.clients.discard(client)
        if client.writer_task:
            client.writer_task.cancel()
        client.writer.close()

    async def start(self, session: Session) -> None:
        self.session = session
        with contextlib.suppress(FileNotFoundError):
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(self._serve, path=str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        log.info("listening on %s", self.socket_path)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = Client(reader, writer)
        client.writer_task = asyncio.create_task(client.write_loop())
        self.clients.add(client)
        try:
            while line := await reader.readline():
                try:
                    msg = json.loads(line)
                except ValueError:
                    client.send(b'{"ev":"error","message":"bad json"}\n')
                    continue
                if not isinstance(msg, dict):
                    continue
                try:
                    reply = await self.session.handle(msg)
                except Exception as e:
                    log.exception("command failed: %s", msg.get("cmd"))
                    reply = {"ev": "error", "message": f"{msg.get('cmd')} failed: {e}"}
                if reply is not None:
                    client.send((json.dumps(reply, separators=(",", ":")) + "\n").encode())
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._drop(client)

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for client in list(self.clients):
            self._drop(client)
        with contextlib.suppress(FileNotFoundError):
            self.socket_path.unlink()
