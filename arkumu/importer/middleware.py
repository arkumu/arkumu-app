"""Compatibility module exposing the SSE middleware."""

from .middleware_sse_backup import SSEAuthMiddleware  # noqa: F401

__all__ = ["SSEAuthMiddleware"]
