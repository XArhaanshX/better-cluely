"""The daemon works with no overlay attached, and clients can't hurt each other."""

import asyncio
import json
import time

import pytest

from wispd import session as session_mod
from wispd.config import Config
from wispd.server import QUEUE_LIMIT, Server
from wispd.stt import Utterance


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.requests = []

    async def start(self):
        pass

    async def close(self):
        pass

    def describe(self):
        return {"backend": "fake"}

    async def stream(self, req):
        self.requests.append(req)
        yield "ok"


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(session_mod, "SESSIONS_DIR", tmp_path / "sessions")
    backend = FakeBackend()
    monkeypatch.setattr(session_mod, "make_backend", lambda c: backend)
    return backend


def test_answers_with_no_client_connected(session, tmp_path):
    """Nothing in the session waits on a UI: with zero clients, a question
    from the other side is still answered."""
    async def run():
        server = Server(tmp_path / "wisp.sock")
        s = session_mod.Session(Config(), server.broadcast)
        now = time.time()
        s._on_utterance(Utterance("them", "Can you explain what a mutex is", now - 1, now, final=True))
        await asyncio.sleep(0.1)
        return s
    s = asyncio.run(run())
    assert len(session.requests) == 1
    assert s.answers[0].done and s.answers[0].text == "ok"


def test_stalled_client_is_dropped_and_others_keep_receiving(session, tmp_path):
    """A client that never reads is cut off once its queue fills; a healthy
    client connected at the same time gets every event."""
    async def run():
        sock = tmp_path / "wisp.sock"
        server = Server(sock)
        s = session_mod.Session(Config(), server.broadcast)
        await server.start(s)

        _, stalled_w = await asyncio.open_unix_connection(str(sock))  # never reads
        healthy_r, healthy_w = await asyncio.open_unix_connection(str(sock))
        await asyncio.sleep(0.05)
        assert len(server.clients) == 2

        received = 0

        async def reader():
            nonlocal received
            while line := await healthy_r.readline():
                if json.loads(line).get("ev") == "level":
                    received += 1

        read_task = asyncio.create_task(reader())
        sent = QUEUE_LIMIT * 4
        for i in range(sent):
            server.broadcast({"ev": "level", "you": 0.1, "them": 0.2, "pad": "x" * 200})
            if i % 200 == 0:
                await asyncio.sleep(0)  # let writers run, as the event loop would
        for _ in range(100):
            if received >= sent:
                break
            await asyncio.sleep(0.02)
        clients_left = len(server.clients)
        read_task.cancel()
        stalled_w.close()
        healthy_w.close()
        await server.close()
        return sent, received, clients_left

    sent, received, clients_left = asyncio.run(run())
    assert clients_left == 1  # the stalled one was dropped
    assert received == sent


def test_broadcast_with_zero_clients_is_a_noop(tmp_path):
    server = Server(tmp_path / "wisp.sock")
    for _ in range(10_000):
        server.broadcast({"ev": "level", "you": 0.1, "them": 0.2})
    assert server.clients == set()
