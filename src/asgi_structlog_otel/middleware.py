import logging
from typing import Any
from collections.abc import Callable

import structlog
from asgi_structlog_otel.extractor import Extractor, extract_otel

logger = logging.getLogger(__name__)




class TraceContextMiddleware:
    def __init__(self, app, extractors: list[Extractor] | None = None):
        self.app = app
        self.extractors = extractors or [extract_otel]

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any]
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
        
        