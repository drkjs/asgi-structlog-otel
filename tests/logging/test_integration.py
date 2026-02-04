"""Integration tests for middleware + logging configuration."""

import json

import structlog

from asgi_structlog_otel import TraceContextMiddleware
from asgi_structlog_otel.logging import FormatterType, GCPFormatter, configure_logging


async def test_middleware_with_json_formatter_includes_trace_context(tracer, capsys):
    """Test that trace context from middleware appears in JSON logs."""
    configure_logging(formatter=FormatterType.JSON)

    async def app(scope, receive, send):
        logger = structlog.get_logger()
        logger.info("test message", key="value")

    middleware = TraceContextMiddleware(app)
    scope = {"type": "http", "path": "/test"}

    with tracer.start_as_current_span("test-span"):
        await middleware(scope, None, None)

    captured = capsys.readouterr()
    log_entry = json.loads(captured.err.strip())

    assert "trace_id" in log_entry
    assert "span_id" in log_entry
    assert log_entry["event"] == "test message"
    assert log_entry["key"] == "value"
    assert len(log_entry["trace_id"]) == 32
    assert len(log_entry["span_id"]) == 16


async def test_middleware_with_gcp_formatter_includes_gcp_fields(tracer, capsys):
    """Test that GCP formatter transforms trace context correctly."""
    configure_logging(formatter=GCPFormatter(project_id="test-project"))

    async def app(scope, receive, send):
        logger = structlog.get_logger()
        logger.info("gcp test")

    middleware = TraceContextMiddleware(app)

    with tracer.start_as_current_span("test-span"):
        await middleware({"type": "http"}, None, None)

    captured = capsys.readouterr()
    log_entry = json.loads(captured.err.strip())

    assert "logging.googleapis.com/trace" in log_entry
    assert "logging.googleapis.com/spanId" in log_entry
    assert log_entry["logging.googleapis.com/trace"].startswith("projects/test-project/traces/")
    assert "trace_id" not in log_entry
    assert "span_id" not in log_entry


async def test_middleware_context_isolation(tracer, capsys):
    """Test context isolation: multiple logs share context, different requests don't."""
    configure_logging(formatter=FormatterType.JSON)

    async def app(scope, receive, send):
        logger = structlog.get_logger()
        logger.info("first log")
        logger.info("second log")

    middleware = TraceContextMiddleware(app)

    # First request
    with tracer.start_as_current_span("span-1"):
        await middleware({"type": "http"}, None, None)

    captured1 = capsys.readouterr()
    lines1 = captured1.err.strip().split("\n")
    req1_log1 = json.loads(lines1[0])
    req1_log2 = json.loads(lines1[1])

    # Multiple logs in same request share context
    assert req1_log1["trace_id"] == req1_log2["trace_id"]
    assert req1_log1["span_id"] == req1_log2["span_id"]

    # Second request with different span
    with tracer.start_as_current_span("span-2"):
        await middleware({"type": "http"}, None, None)

    captured2 = capsys.readouterr()
    req2_log = json.loads(captured2.err.strip().split("\n")[0])

    # Different requests have different context
    assert req1_log1["span_id"] != req2_log["span_id"]

    # Context is clean after requests
    final_context = structlog.contextvars.get_contextvars()
    assert "trace_id" not in final_context
    assert "span_id" not in final_context


async def test_no_active_span_no_trace_context_in_logs(capsys):
    """Test that logs without active span don't have trace context."""
    configure_logging(formatter=FormatterType.JSON)

    async def app(scope, receive, send):
        logger = structlog.get_logger()
        logger.info("no span")

    middleware = TraceContextMiddleware(app)
    await middleware({"type": "http"}, None, None)

    captured = capsys.readouterr()
    log_entry = json.loads(captured.err.strip())

    assert "trace_id" not in log_entry
    assert "span_id" not in log_entry
    assert log_entry["event"] == "no span"
