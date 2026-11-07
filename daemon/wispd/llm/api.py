"""Anthropic API backend, through the official SDK.

Latency choices:
- One long-lived client whose connection stays open for 5 minutes, so a
  question after a pause doesn't pay for a new TLS handshake (the SDK's
  default keep-alive is 5 s).
- The system prompt and the context (notes + transcript) carry cache
  breakpoints. The transcript only grows, so most of it is read from the
  cache on the next request.
- Effort defaults to "low": these are glanceable answers, not essays.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
from collections.abc import AsyncIterator

import anthropic
import httpx2

from ..config import Config
from .base import BackendError, Request

log = logging.getLogger(__name__)

# Models that take the server-side refusal fallback ("default" form).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-opus-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
KEEPALIVE_S = 300.0


NO_KEY = "No API key. Put one in the file named by api_key_file, or set ANTHROPIC_API_KEY."


def _is_missing_auth(e: Exception) -> bool:
    # With no credentials at all the SDK raises TypeError at request time.
    return isinstance(e, TypeError) and "authentication" in str(e)


class ApiBackend:
    name = "api"

    def __init__(self, cfg: Config):
        self.model = cfg.resolved_model()
        self.effort = cfg.effort
        http = anthropic.DefaultAsyncHttpxClient(
            limits=httpx2.Limits(max_connections=20, max_keepalive_connections=4,
                                 keepalive_expiry=KEEPALIVE_S))
        # api_key=None falls back to the SDK's own credential lookup.
        self.client = anthropic.AsyncAnthropic(api_key=cfg.api_key(), http_client=http,
                                               max_retries=1)
        self._warm_task: asyncio.Task | None = None

    def describe(self) -> dict:
        return {"backend": self.name, "model": self.model, "effort": self.effort}

    async def start(self) -> None:
        self._warm_task = asyncio.create_task(self._keep_warm())

    async def _keep_warm(self) -> None:
        """Hold the connection open with a free models request."""
        while True:
            try:
                await self.client.models.retrieve(self.model)
            except anthropic.AuthenticationError:
                log.error("API key rejected; the API backend will not work")
                return
            except TypeError as e:
                if _is_missing_auth(e):
                    log.error(NO_KEY)
                    return
                raise
            except anthropic.APIError as e:
                log.debug("keep-warm failed: %s", e)
            await asyncio.sleep(KEEPALIVE_S - 30)

    def _params(self, req: Request) -> dict:
        content: list[dict] = []
        if req.context:
            content.append({"type": "text", "text": req.context,
                            "cache_control": {"type": "ephemeral"}})
        if req.image_jpeg:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(req.image_jpeg).decode()}})
        content.append({"type": "text", "text": req.prompt})
        return dict(
            model=self.model,
            max_tokens=8000,
            system=[{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
            output_config={"effort": self.effort},
        )

    async def stream(self, req: Request) -> AsyncIterator[str]:
        params = self._params(req)
        try:
            if self.model in FALLBACK_MODELS:
                ctx = self.client.beta.messages.stream(
                    **params, betas=[FALLBACK_BETA], fallbacks="default")
            else:
                ctx = self.client.messages.stream(**params)
            async with ctx as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
            if final.stop_reason == "refusal":
                yield "\n\n_(The model declined to answer this.)_"
            u = final.usage
            log.info("api usage: in=%s cache_read=%s cache_write=%s out=%s",
                     u.input_tokens, u.cache_read_input_tokens,
                     u.cache_creation_input_tokens, u.output_tokens)
        except TypeError as e:
            if _is_missing_auth(e):
                raise BackendError(NO_KEY) from e
            raise
        except anthropic.AuthenticationError as e:
            raise BackendError("The API key was rejected.") from e
        except anthropic.RateLimitError as e:
            raise BackendError("Rate limited by the API; try again in a moment.") from e
        except anthropic.APIStatusError as e:
            raise BackendError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise BackendError("Cannot reach the Anthropic API.") from e

    async def close(self) -> None:
        if self._warm_task:
            self._warm_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._warm_task
        await self.client.close()
