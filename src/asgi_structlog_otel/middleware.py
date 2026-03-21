import logging
from typing import Any
from collections.abc import Awaitable, Callable

import structlog
from asgi_structlog_otel.extractor import Extractor, extract_otel

logger = logging.getLogger(__name__)

# ASGI application type per the ASGI spec
ASGIApp = Callable[
    [dict[str, Any], Callable[[], Awaitable[Any]], Callable[[dict[str, Any]], Awaitable[Any]]],
    Awaitable[None],
]


class TraceContextMiddleware:
    def __init__(self, app: ASGIApp, extractors: list[Extractor] | None = None):
        self.app = app
        if extractors is not None:
            self.extractors = extractors
        else:
            try:
                import opentelemetry  # noqa: F401
            except ImportError:
                raise ImportError(
                    "opentelemetry-api is required when using the default extract_otel extractor. "
                    "Either install it with: pip install asgi-structlog-otel[otel] "
                    "or pass explicit extractors (e.g., extractors=[extract_from_traceparent])."
                )
            self.extractors = [extract_otel]

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[Any]],
        send: Callable[[dict[str, Any]], Awaitable[Any]],
    ):
        
        # The ASGI specification only supports HTTP/WebSocket and Lifespan - if we don't have one of the first two, we don't instrument. 
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return None
        
        ctx: dict[str, Any] = {}

        for extractor in self.extractors:
            try:
                data = extractor(scope, ctx)
            except Exception:
                logger.warning(
                    "Extractor failed: %s",
                    extractor.__name__ if hasattr(extractor, '__name__') else str(extractor),
                    exc_info=True
                )
                continue
            if data:
                ctx.update(data)
        
        structlog.contextvars.bind_contextvars(**ctx)

        try:
            await self.app(scope, receive, send)
        finally:
            structlog.contextvars.unbind_contextvars(*ctx.keys())
        
        