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


# Custom Extractors Tests

async def test_middleware_multiple_extractors_execution_and_merging(tracer):
    """Test that custom extractors execute in order and merge data correctly."""
    execution_order = []
    bound_context = {}

    def extractor_one(scope):
        execution_order.append(1)
        return {"key1": "value1", "shared": "from_one"}

    def extractor_two(scope):
        execution_order.append(2)
        return {"key2": "value2", "shared": "from_two"}

    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())

    middleware = TraceContextMiddleware(app, extractors=[extractor_one, extractor_two])

    scope = {"type": "http"}
    await middleware(scope, None, None)

    # Verify execution order
    assert execution_order == [1, 2]

    # Verify all data is bound
    assert bound_context["key1"] == "value1"
    assert bound_context["key2"] == "value2"

    # Verify later extractor overwrites shared keys
    assert bound_context["shared"] == "from_two"


# Error Handling Tests

async def test_middleware_extractor_exception_continues(tracer, caplog):
    """Test that middleware continues and logs when an extractor raises an exception."""
    import logging
    bound_context = {}

    def failing_extractor(scope):
        raise ValueError("Extractor failed")

    def working_extractor(scope):
        return {"key": "value"}

    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())

    middleware = TraceContextMiddleware(
        app,
        extractors=[failing_extractor, working_extractor]
    )

    scope = {"type": "http"}

    with caplog.at_level(logging.WARNING):
        await middleware(scope, None, None)

    # Working extractor should still execute
    assert bound_context["key"] == "value"

    # Failure should be logged
    assert "Extractor failed" in caplog.text
    assert "failing_extractor" in caplog.text


async def test_middleware_all_extractors_fail(tracer, caplog):
    """Test that middleware works and logs when all extractors fail."""
    import logging
    bound_context = {}
    app_called = False

    def failing_extractor(scope):
        raise RuntimeError("Failed")

    async def app(scope, receive, send):
        nonlocal app_called
        app_called = True
        bound_context.update(structlog.contextvars.get_contextvars())

    middleware = TraceContextMiddleware(app, extractors=[failing_extractor])

    scope = {"type": "http"}

    with caplog.at_level(logging.WARNING):
        await middleware(scope, None, None)

    # App should still be called
    assert app_called
    # No context should be bound
    assert len(bound_context) == 0

    # Failure should be logged
    assert "Extractor failed" in caplog.text


# Context Cleanup Tests

async def test_middleware_unbinds_context_after_request(tracer):
    """Test that context is unbound after request completes."""

    async def app(scope, receive, send):
        # Context should be bound during request
        ctx = structlog.contextvars.get_contextvars()
        assert "trace_id" in ctx

    middleware = TraceContextMiddleware(app)

    scope = {"type": "http"}

    with tracer.start_as_current_span("test-span"):
        await middleware(scope, None, None)

    # Context should be unbound after middleware completes
    ctx_after = structlog.contextvars.get_contextvars()
    assert "trace_id" not in ctx_after
    assert "span_id" not in ctx_after


async def test_middleware_unbinds_context_on_app_exception(tracer):
    """Test that context is unbound even when app raises an exception."""

    async def failing_app(scope, receive, send):
        raise RuntimeError("App failed")

    middleware = TraceContextMiddleware(failing_app)

    scope = {"type": "http"}

    with tracer.start_as_current_span("test-span"):
        try:
            await middleware(scope, None, None)
        except RuntimeError:
            pass  # Expected

    # Context should still be unbound
    ctx_after = structlog.contextvars.get_contextvars()
    assert "trace_id" not in ctx_after
    assert "span_id" not in ctx_after


async def test_middleware_context_isolation_between_requests(tracer):
    """Test that context from one request doesn't leak to another."""

    def custom_extractor(scope):
        return {"request_id": scope.get("request_id")}

    contexts = []

    async def app(scope, receive, send):
        contexts.append(dict(structlog.contextvars.get_contextvars()))

    middleware = TraceContextMiddleware(app, extractors=[custom_extractor])

    # First request
    scope1 = {"type": "http", "request_id": "req-1"}
    await middleware(scope1, None, None)

    # Second request
    scope2 = {"type": "http", "request_id": "req-2"}
    await middleware(scope2, None, None)

    # Each request should have its own context
    assert contexts[0]["request_id"] == "req-1"
    assert contexts[1]["request_id"] == "req-2"

    # Context should not leak after both requests
    final_ctx = structlog.contextvars.get_contextvars()
    assert "request_id" not in final_ctx


# Edge Cases Tests

async def test_middleware_no_active_span():
    """Test middleware behavior when there's no active OpenTelemetry span."""
    bound_context = {}

    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())

    middleware = TraceContextMiddleware(app)  # Using default extract_otel

    scope = {"type": "http"}

    # Call without starting a span
    await middleware(scope, None, None)

    # Should not bind trace context
    assert "trace_id" not in bound_context
    assert "span_id" not in bound_context


async def test_middleware_extractor_returns_none():
    """Test that extractor returning None doesn't break middleware."""
    bound_context = {}

    def none_extractor(scope):
        return None

    def working_extractor(scope):
        return {"key": "value"}

    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())

    middleware = TraceContextMiddleware(
        app,
        extractors=[none_extractor, working_extractor]
    )

    scope = {"type": "http"}
    await middleware(scope, None, None)

    # Working extractor should still work
    assert bound_context["key"] == "value"


async def test_middleware_extractor_returns_empty_dict():
    """Test that extractor returning empty dict doesn't break middleware."""
    bound_context = {}

    def empty_extractor(scope):
        return {}

    def working_extractor(scope):
        return {"key": "value"}

    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())

    middleware = TraceContextMiddleware(
        app,
        extractors=[empty_extractor, working_extractor]
    )

    scope = {"type": "http"}
    await middleware(scope, None, None)

    assert bound_context["key"] == "value"


async def test_middleware_empty_extractor_list():
    """Test middleware with empty extractor list."""
    bound_context = {}

    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())

    middleware = TraceContextMiddleware(app, extractors=[])

    scope = {"type": "http"}
    await middleware(scope, None, None)

    # No context should be bound
    assert len(bound_context) == 0