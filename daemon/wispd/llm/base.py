from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Request:
    system: str
    # Stable part: user notes plus the transcript so far. It only grows, so
    # it makes a good cache prefix.
    context: str
    # What is being asked this time.
    prompt: str
    image_jpeg: bytes | None = None


class BackendError(RuntimeError):
    pass


class Backend(Protocol):
    name: str

    async def start(self) -> None: ...

    def stream(self, req: Request) -> AsyncIterator[str]: ...

    async def close(self) -> None: ...

    def describe(self) -> dict: ...
