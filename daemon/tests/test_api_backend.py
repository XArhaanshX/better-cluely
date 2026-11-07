"""The API backend against a local fake of the Messages endpoint.

The real SDK runs end to end (request building, SSE parsing, errors);
only the network is replaced, by an httpx2 MockTransport. No key needed.
"""

import asyncio
import json

import httpx2
import pytest

import wispd.llm.api as api_mod
from wispd.config import Config
from wispd.llm import BackendError, Request
from wispd.llm.api import ApiBackend


def sse(*events: dict) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def message_stream(texts, stop_reason="end_turn"):
    return sse(
        {"type": "message_start", "message": {
            "id": "msg_test", "type": "message", "role": "assistant", "model": "test",
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 1,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        *({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}}
          for t in texts),
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
         "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    )


@pytest.fixture
def fake_api(monkeypatch, tmp_path):
    """Route the backend's HTTP client to a handler; returns the captured requests."""
    seen = []
    state = {"respond": lambda req: httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, content=message_stream(["Hello", " world"]))}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.startswith("/v1/models"):
            return httpx2.Response(200, json={"id": "m", "type": "model", "display_name": "m",
                                              "created_at": "2026-01-01T00:00:00Z"})
        seen.append(request)
        return state["respond"](request)

    real = api_mod.anthropic.DefaultAsyncHttpxClient
    monkeypatch.setattr(api_mod.anthropic, "DefaultAsyncHttpxClient",
                        lambda **kw: real(transport=httpx2.MockTransport(handler), **kw))
    key = tmp_path / "key"
    key.write_text("sk-ant-test")

    def make(**cfg):
        return ApiBackend(Config(backend="api", api_key_file=str(key), **cfg))
    return make, seen, state


async def collect(backend, req):
    out = ""
    async for t in backend.stream(req):
        out += t
    await backend.close()
    return out


REQ = Request(system="sys prompt", context="## Live transcript\n[00:01] Them: hi",
              prompt="What should I say?", image_jpeg=b"\xff\xd8jpegbytes")


def test_streams_text_and_builds_a_cached_request(fake_api):
    make, seen, _ = fake_api
    text = asyncio.run(collect(make(), REQ))
    assert text == "Hello world"
    body = json.loads(seen[0].content)
    assert body["model"] == "claude-opus-5-5"  # "smart" is the API default
    assert body["output_config"] == {"effort": "low"}
    assert body["stream"] is True
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    context, image, prompt = body["messages"][0]["content"]
    assert context["cache_control"] == {"type": "ephemeral"} and "Them: hi" in context["text"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    assert prompt == {"type": "text", "text": "What should I say?"}
    # Opus gets the server-side refusal fallback.
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen[0].headers["anthropic-beta"]
    # SDK 2.x sends the key as a bearer token, not x-api-key.
    assert seen[0].headers["authorization"] == "Bearer sk-ant-test"


def test_fast_preset_uses_haiku_without_fallbacks(fake_api):
    make, seen, _ = fake_api
    asyncio.run(collect(make(preset="fast"), Request("s", "", "q")))
    body = json.loads(seen[0].content)
    assert body["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in body
    assert "server-side-fallback" not in seen[0].headers.get("anthropic-beta", "")
    assert len(body["messages"][0]["content"]) == 1  # no context, no image


def test_refusal_is_reported_in_the_answer(fake_api):
    make, _, state = fake_api
    state["respond"] = lambda req: httpx2.Response(
        200, headers={"content-type": "text/event-stream"},
        content=message_stream(["Partial"], stop_reason="refusal"))
    text = asyncio.run(collect(make(), REQ))
    assert text.startswith("Partial") and "declined" in text


@pytest.mark.parametrize("status,message", [
    (401, "rejected"),
    (429, "Rate limited"),
    (500, "API error 500"),
])
def test_http_errors_become_readable_messages(fake_api, status, message):
    make, _, state = fake_api
    state["respond"] = lambda req: httpx2.Response(
        status, headers={"retry-after": "0"},
        json={"type": "error", "error": {"type": "x", "message": "nope"}})
    with pytest.raises(BackendError, match=message):
        asyncio.run(collect(make(), REQ))
