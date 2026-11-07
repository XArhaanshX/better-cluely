"""Session logic with a fake backend: auto-answers, instant Ask, cancelling."""

import asyncio
import json
import time

import pytest

from wispd import session as session_mod
from wispd.config import Config
from wispd.stt import Utterance


class FakeBackend:
    name = "fake"

    def __init__(self, delay=0.01):
        self.requests = []
        self.delay = delay

    async def start(self):
        pass

    async def close(self):
        pass

    def describe(self):
        return {"backend": "fake"}

    async def stream(self, req):
        self.requests.append(req)
        for word in ("one ", "two ", "three"):
            await asyncio.sleep(self.delay)
            yield word


@pytest.fixture
def make_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(session_mod, "SESSIONS_DIR", tmp_path / "sessions")

    def make(**cfg):
        events = []
        backend = FakeBackend(cfg.pop("delay", 0.01))
        monkeypatch.setattr(session_mod, "make_backend", lambda c: backend)
        s = session_mod.Session(Config(**cfg), events.append)
        return s, backend, events
    return make


def say(s, source, text):
    now = time.time()
    s._on_utterance(Utterance(source, text, now - 1, now, final=True))


def kinds(events, name):
    return [e for e in events if e["ev"] == name]


def test_question_from_them_starts_an_auto_answer(make_session):
    async def run():
        s, backend, events = make_session()
        say(s, "them", "Can you walk me through your last project")
        await asyncio.sleep(0.1)
        return s, backend, events
    s, backend, events = asyncio.run(run())
    starts = kinds(events, "answer.start")
    assert len(starts) == 1 and starts[0]["auto"]
    assert "walk me through your last project" in backend.requests[0].prompt
    assert s.answers[0].text == "one two three"


def test_statement_does_not_trigger(make_session):
    async def run():
        s, backend, events = make_session()
        say(s, "them", "Okay that sounds good to me")
        say(s, "you", "What do you think about the roadmap")  # the user, not them
        await asyncio.sleep(0.05)
        return backend
    assert asyncio.run(run()).requests == []


def test_ask_shows_the_auto_answer_instantly_then_asks_fresh(make_session):
    async def run():
        s, backend, events = make_session()
        say(s, "them", "How would you design a rate limiter")
        await asyncio.sleep(0.005)  # still streaming
        await s.ask(screenshot=False)
        focus = kinds(events, "answer.focus")
        n_after_first_ask = len(backend.requests)
        await s.ask(screenshot=False)
        await asyncio.sleep(0.1)
        return s, backend, events, focus, n_after_first_ask
    s, backend, events, focus, n1 = asyncio.run(run())
    assert len(focus) == 1 and focus[0]["id"] == s.answers[0].id
    assert n1 == 1  # the first Ask made no new request
    assert len(backend.requests) == 2 and s.answers[1].kind == "assist"


def test_split_question_is_merged(make_session):
    async def run():
        s, backend, events = make_session(delay=0.05)
        say(s, "them", "So what would you do if the database")
        await asyncio.sleep(0.01)
        say(s, "them", "how would you handle a failover")
        await asyncio.sleep(0.3)
        return s, backend
    s, backend = asyncio.run(run())
    assert s.answers[0].cancelled
    assert "database how would you handle a failover" in backend.requests[-1].prompt


def test_typed_question_replaces_running_manual_answer(make_session):
    async def run():
        s, backend, events = make_session(delay=0.05)
        await s.ask(text="first question", screenshot=False)
        await asyncio.sleep(0.01)
        await s.ask(text="second question", screenshot=False)
        await asyncio.sleep(0.3)
        return s
    s = asyncio.run(run())
    assert s.answers[0].cancelled and not s.answers[1].cancelled
    assert s.answers[1].text == "one two three"


def test_settings_persist(make_session, tmp_path):
    async def run():
        s, _, events = make_session()
        await s.set("mode", "interview")
        await s.set("bogus", 1)
        return events
    events = asyncio.run(run())
    assert json.loads((tmp_path / "state.json").read_text())["mode"] == "interview"
    assert any(e["ev"] == "error" for e in events)


def test_speaker_echo_is_not_transcribed_as_the_user(make_session):
    import numpy as np
    from wispd.audio import Frame

    class FakeCapture:
        def __init__(self, source, frames):
            self.source, self._frames = source, frames

        async def frames(self):
            for f in self._frames:
                yield f

    class FakeStt:
        def __init__(self):
            self.pushed = []

        def push(self, source, samples, rms):
            self.pushed.append((source, rms))

    async def run(echo_risk):
        s, _, _ = make_session()
        s.stt = FakeStt()
        s._echo_risk = echo_risk
        z = np.zeros(320, dtype=np.float32)
        await s._pump(FakeCapture("them", [Frame("them", z, 0.20)]))
        await s._pump(FakeCapture("you", [Frame("you", z, 0.05),    # echo of them
                                          Frame("you", z, 0.40)]))  # user talking over them
        return [rms for src, rms in s.stt.pushed if src == "you"]

    assert asyncio.run(run(True)) == [0.0, 0.40]
    assert asyncio.run(run(False)) == [0.05, 0.40]  # headphones: keep everything


def test_notes_are_saved_as_markdown(make_session, tmp_path):
    async def run():
        s, backend, events = make_session(notes_dir=str(tmp_path / "notes"))
        say(s, "them", "Let's ship the beta on Friday")
        say(s, "you", "I'll write the release notes")
        await s.ask(action="notes", screenshot=False)
        await asyncio.sleep(0.1)
        return s, events
    s, events = asyncio.run(run())
    done = [e for e in events if e["ev"] == "answer.done" and e.get("path")]
    assert len(done) == 1
    text = open(done[0]["path"]).read()
    assert text.startswith("# Notes, ")
    assert "one two three" in text
    assert "Them: Let's ship the beta on Friday" in text


# -- echo cancellation wiring ------------------------------------------------

class _FakeCapture:
    started = []

    def __init__(self, source, device=None):
        self.source, self.device = source, device

    async def start(self):
        _FakeCapture.started.append((self.source, self.device))

    async def frames(self):
        await asyncio.Event().wait()
        yield  # pragma: no cover

    async def stop(self):
        pass


class _FakeWatcher:
    sink = ""

    def __init__(self, on_change):
        self.on_change = on_change
        self.source = "mic"

    async def start(self):
        pass

    async def stop(self):
        pass


class _FakeAec:
    def __init__(self, ok=True):
        self.ok, self.running, self.starts = ok, False, 0

    async def start(self):
        self.starts += 1
        self.running = self.ok
        return self.ok

    async def stop(self):
        self.running = False


@pytest.fixture
def audio_fakes(monkeypatch):
    _FakeCapture.started = []
    monkeypatch.setattr(session_mod, "AudioCapture", _FakeCapture)
    monkeypatch.setattr(session_mod, "DeviceWatcher", _FakeWatcher)

    def setup(s, sink, aec_ok=True):
        _FakeWatcher.sink = sink
        s._aec = _FakeAec(aec_ok)
        return s._aec
    return setup


SPEAKERS = "alsa_output.pci-0000_00_1f.3-platform-sof_sdw.HiFi__Speaker__sink"
HEADPHONES = "alsa_output.pci-0000_00_1f.3-platform-sof_sdw.HiFi__Headphones__sink"


def test_speakers_record_the_mic_through_echo_cancellation(make_session, audio_fakes):
    async def run():
        s, _, _ = make_session()
        fake = audio_fakes(s, SPEAKERS)
        await s.listen(True)
        status = s.status()
        await s.listen(False)
        return fake, status
    fake, status = asyncio.run(run())
    assert ("you", session_mod.aec.SOURCE_NAME) in _FakeCapture.started
    assert ("them", None) in _FakeCapture.started
    assert status["echo_cancel"] is True
    assert not fake.running  # stopped with listening


def test_headphones_use_the_plain_mic(make_session, audio_fakes):
    async def run():
        s, _, _ = make_session()
        fake = audio_fakes(s, HEADPHONES)
        await s.listen(True)
        await s.listen(False)
        return fake
    fake = asyncio.run(run())
    assert ("you", None) in _FakeCapture.started
    assert fake.starts == 0


def test_falls_back_when_echo_cancellation_cannot_start(make_session, audio_fakes):
    async def run():
        s, _, _ = make_session()
        audio_fakes(s, SPEAKERS, aec_ok=False)
        await s.listen(True)
        return s
    s = asyncio.run(run())
    assert ("you", None) in _FakeCapture.started
    assert s._echo_risk and not s._aec.running  # level heuristic stays in charge


def test_switching_to_headphones_mid_call_turns_it_off(make_session, audio_fakes):
    async def run():
        s, _, _ = make_session()
        fake = audio_fakes(s, SPEAKERS)
        await s.listen(True)
        _FakeCapture.started.clear()
        await s._devices_changed(HEADPHONES, "mic", (SPEAKERS, "mic"))
        return fake
    fake = asyncio.run(run())
    assert not fake.running
    assert ("you", None) in _FakeCapture.started


def test_echo_cancel_off_never_starts_it(make_session, audio_fakes):
    async def run():
        s, _, _ = make_session(echo_cancel="off")
        fake = audio_fakes(s, SPEAKERS)
        await s.listen(True)
        return fake
    fake = asyncio.run(run())
    assert fake.starts == 0 and ("you", None) in _FakeCapture.started
