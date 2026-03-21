import logging

import structlog

from asgi_structlog_otel import TraceContextMiddleware


async def test_middleware_binds_context_for_http_and_websocket(tracer):
    """Test that HTTP and WebSocket requests bind trace context, lifespan does not."""
    bound_contexts = []

    async def app(scope, receive, send):
        bound_contexts.append(dict(structlog.contextvars.get_contextvars()))

    middleware = TraceContextMiddleware(app)

    with tracer.start_as_current_span("test-span"):
        # HTTP request
        await middleware({"type": "http", "path": "/test"}, None, None)
        # WebSocket request
        await middleware({"type": "websocket", "path": "/ws"}, None, None)
        # Lifespan event (should not bind)
        await middleware({"type": "lifespan"}, None, None)

    # HTTP and WebSocket should have trace context
    assert "trace_id" in bound_contexts[0]
    assert "span_id" in bound_contexts[0]
    assert len(bound_contexts[0]["trace_id"]) == 32
    assert len(bound_contexts[0]["span_id"]) == 16

    assert "trace_id" in bound_contexts[1]
    assert "span_id" in bound_contexts[1]

    # Lifespan should not have trace context
    assert "trace_id" not in bound_contexts[2]
    assert "span_id" not in bound_contexts[2]


async def test_middleware_multiple_extractors_execution_and_merging(tracer):
    """Test that custom extractors execute in order and merge data correctly."""
    execution_order = []
    bound_context = {}

    def extractor_one(scope, context):
        execution_order.append(1)
        return {"key1": "value1", "shared": "from_one"}

    def extractor_two(scope, context):
        execution_order.append(2)
        return {"key2": "value2", "shared": "from_two"}

    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())

    middleware = TraceContextMiddleware(app, extractors=[extractor_one, extractor_two])

    await middleware({"type": "http"}, None, None)

    # Verify execution order
    assert execution_order == [1, 2]

    # Verify all data is bound and later extractor overwrites shared keys
    assert bound_context["key1"] == "value1"
    assert bound_context["key2"] == "value2"
    assert bound_context["shared"] == "from_two"


async def test_middleware_extractor_error_handling(tracer, caplog):
    """Test that middleware continues and logs when extractors fail."""
    bound_context = {}
    app_called = False

    def failing_extractor(scope, context):
        raise ValueError("Extractor failed")

    def working_extractor(scope, context):
        return {"key": "value"}

    async def app(scope, receive, send):
        nonlocal app_called
        app_called = True
        bound_context.update(structlog.contextvars.get_contextvars())

    # Test with one failing, one working
    middleware = TraceContextMiddleware(
        app,
        extractors=[failing_extractor, working_extractor]
    )

    with caplog.at_level(logging.WARNING):
        await middleware({"type": "http"}, None, None)

    assert bound_context["key"] == "value"
    assert "Extractor failed" in caplog.text
    assert "failing_extractor" in caplog.text

    # Test with all extractors failing
    bound_context.clear()
    app_called = False
    caplog.clear()

    middleware_all_fail = TraceContextMiddleware(app, extractors=[failing_extractor])

    with caplog.at_level(logging.WARNING):
        await middleware_all_fail({"type": "http"}, None, None)

    assert app_called
    assert len(bound_context) == 0
    assert "Extractor failed" in caplog.text


async def test_middleware_unbinds_context(tracer):
    """Test that context is unbound after request, even on exception."""
    context_during_request = {}

    async def app(scope, receive, send):
        context_during_request.update(structlog.contextvars.get_contextvars())
        assert "trace_id" in context_during_request

    middleware = TraceContextMiddleware(app)

    # Normal request
    with tracer.start_as_current_span("test-span"):
        await middleware({"type": "http"}, None, None)

    ctx_after = structlog.contextvars.get_contextvars()
    assert "trace_id" not in ctx_after
    assert "span_id" not in ctx_after

    # Request with exception
    async def failing_app(scope, receive, send):
        raise RuntimeError("App failed")

    middleware_fail = TraceContextMiddleware(failing_app)

    with tracer.start_as_current_span("test-span"):
        try:
            await middleware_fail({"type": "http"}, None, None)
        except RuntimeError:
            pass

    ctx_after_fail = structlog.contextvars.get_contextvars()
    assert "trace_id" not in ctx_after_fail
    assert "span_id" not in ctx_after_fail


async def test_middleware_no_active_span():
    """Test middleware behavior when there's no active OpenTelemetry span."""
    bound_context = {}

    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())

    middleware = TraceContextMiddleware(app)

    # Call without starting a span
    await middleware({"type": "http"}, None, None)

    assert "trace_id" not in bound_context
    assert "span_id" not in bound_context


async def test_middleware_extractor_edge_cases():
    """Test extractors returning None, empty dict, or empty extractor list."""
    bound_context = {}

    def none_extractor(scope, context):
        return None

    def empty_extractor(scope, context):
        return {}

    def working_extractor(scope, context):
        return {"key": "value"}

    async def app(scope, receive, send):
        bound_context.update(structlog.contextvars.get_contextvars())

    # None and empty dict extractors shouldn't break working ones
    middleware = TraceContextMiddleware(
        app,
        extractors=[none_extractor, empty_extractor, working_extractor]
    )

    await middleware({"type": "http"}, None, None)
    assert bound_context["key"] == "value"

    # Empty extractor list
    bound_context.clear()
    middleware_empty = TraceContextMiddleware(app, extractors=[])

    await middleware_empty({"type": "http"}, None, None)
    assert len(bound_context) == 0
