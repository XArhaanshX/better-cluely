"""LLM backends. Both stream text deltas for a Request."""

from .base import Backend, BackendError, Request

__all__ = ["Backend", "BackendError", "Request", "make_backend"]


def make_backend(cfg) -> Backend:
    if cfg.backend == "api":
        from .api import ApiBackend
        return ApiBackend(cfg)
    from .claude_code import ClaudeCodeBackend
    return ClaudeCodeBackend(cfg)
