import structlog
from asgi_structlog_otel import TraceContextMiddleware


async def test_middleware_http_request_binds_context(tracer):
    """Test that HTTP requests bind trace context."""
    # Track what context was bound
    bound_context = {}
    
    async def app(scope, receive, send):
        # Capture the current context
        bound_context.update(structlog.contextvars.get_contextvars())
    
    middleware = TraceContextMiddleware(app)
    
    scope = {"type": "http", "path": "/test"}
    
    with tracer.start_as_current_span("test-span"):
        await middleware(scope, None, None)
    
    # Verify trace context was bound
    assert "trace_id" in bound_context
    assert "span_id" in bound_context
    assert len(bound_context["trace_id"]) == 32
    assert len(bound_context["span_id"]) == 16


async def test_middleware_websocket_request_binds_context(tracer):
    """Test that WebSocket requests bind trace context."""
    bound_context = {}
    
    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())
    
    middleware = TraceContextMiddleware(app)
    
    scope = {"type": "websocket", "path": "/ws"}
    
    with tracer.start_as_current_span("test-span"):
        await middleware(scope, None, None)
    
    assert "trace_id" in bound_context
    assert "span_id" in bound_context

async def test_middleware_lifespan_events_not_instrumented(tracer):
    """Test that lifespan events skip instrumentation."""
    bound_context = {}
    
    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())
    
    with tracer.start_as_current_span("test-span"):
        middleware = TraceContextMiddleware(app)
    
    scope = {"type": "lifespan"}
    await middleware(scope, None, None)
    
    assert "trace_id" not in bound_context
    assert "span_id" not in bound_context