import structlog
from asgi_structlog_otel.extractor import Extractor, extract_otel



class TraceContextMiddelware:
    def __init__(self, app, extractors: list[Extractor] | None = None):
        self.app = app
        self.extractors = extractors or [extract_otel]

    async def __call__(self, scope, receive, send):
        
        # The ASGI specification only supports HTTP/WebSocket and Lifespan - if we don't have one of the first two, we don't instrument. 
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return None
        
        ctx = {}

        for extractor in self.extractors:
            try:
                data = extractor(scope)
            except Exception as e:
                pass 
            if data:
                ctx.update(data)
        
        structlog.contextvars.bind_contextvars(**ctx)

        try:
            await self.app(scope, receive, send)
        finally:
            structlog.contextvars.unbind_contextvars(ctx.keys())
        
        