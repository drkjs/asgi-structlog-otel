"""Tests for configure_logging function and formatters."""

import json
import logging
import os

import pytest
import structlog

from asgi_structlog_otel.logging import FormatterType, GCPFormatter
from asgi_structlog_otel.logging.configure import configure_logging


# Formatter Output Tests


def test_json_formatter_produces_valid_json(capsys):
    """Test that JSON formatter produces parseable JSON output."""
    configure_logging(formatter=FormatterType.JSON)

    logger = structlog.get_logger()
    logger.info("test message", key="value", number=42)

    captured = capsys.readouterr()
    log_entry = json.loads(captured.err.strip())

    assert log_entry["event"] == "test message"
    assert log_entry["key"] == "value"
    assert log_entry["number"] == 42
    assert log_entry["level"] == "info"


def test_console_formatter_produces_human_readable_output(capsys):
    """Test that console formatter produces non-JSON, readable output."""
    configure_logging(formatter=FormatterType.CONSOLE)

    logger = structlog.get_logger()
    logger.info("test message", key="value")

    captured = capsys.readouterr()
    output = captured.err.strip()

    # Should NOT be valid JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(output)

    # Should contain the event and key in readable form
    assert "test message" in output
    assert "key" in output
    assert "value" in output


def test_auto_formatter_tty_detection(monkeypatch, capsys):
    """Test that AUTO formatter selects format based on TTY status."""
    # Non-TTY should use JSON
    monkeypatch.setattr("sys.stderr.isatty", lambda: False)
    configure_logging(formatter=FormatterType.AUTO)

    logger = structlog.get_logger()
    logger.info("non-tty test")

    captured = capsys.readouterr()
    log_entry = json.loads(captured.err.strip())
    assert log_entry["event"] == "non-tty test"

    # TTY should use console (not JSON)
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)
    configure_logging(formatter=FormatterType.AUTO)

    logger = structlog.get_logger()
    logger.info("tty test")

    captured = capsys.readouterr()
    output = captured.err.strip()

    with pytest.raises(json.JSONDecodeError):
        json.loads(output)
    assert "tty test" in output


def test_custom_formatter(capsys):
    """Test that custom Formatter protocol implementations work."""

    class IndentedSortedJSONFormatter:
        def get_processors(self):
            return [structlog.processors.JSONRenderer(indent=2, sort_keys=True)]

    configure_logging(formatter=IndentedSortedJSONFormatter())

    logger = structlog.get_logger()
    logger.info("test", z_key="last", a_key="first")

    captured = capsys.readouterr()
    output = captured.err

    # Should be indented (contains newlines)
    assert "\n" in output

    # Should be valid JSON with sorted keys
    log_entry = json.loads(output)
    assert log_entry["event"] == "test"
    assert output.index('"a_key"') < output.index('"z_key"')


# Log Level Tests


def test_log_level_filtering(capsys):
    """Test that log level filters messages appropriately."""
    configure_logging(formatter=FormatterType.JSON, level=logging.WARNING)

    stdlib_logger = logging.getLogger("test.level")
    stdlib_logger.info("should not appear")
    stdlib_logger.warning("warning message")
    stdlib_logger.error("error message")

    captured = capsys.readouterr()
    output = captured.err

    assert "should not appear" not in output
    assert "warning message" in output
    assert "error message" in output


# Stdlib Integration Tests


def test_stdlib_logging_gets_structlog_formatting(capsys):
    """Test that stdlib logs are formatted through structlog processors."""
    configure_logging(formatter=FormatterType.JSON, configure_stdlib=True)

    stdlib_logger = logging.getLogger("test.stdlib")
    stdlib_logger.info("stdlib message")

    captured = capsys.readouterr()
    log_entry = json.loads(captured.err.strip())

    assert log_entry["event"] == "stdlib message"
    assert log_entry["level"] == "info"


def test_formatter_applied_when_stdlib_disabled(capsys):
    """Test that formatter is applied when stdlib integration is disabled."""
    configure_logging(formatter=FormatterType.JSON, configure_stdlib=False)

    logger = structlog.get_logger()
    logger.info("test message", key="value")

    # PrintLoggerFactory outputs to stdout
    captured = capsys.readouterr()
    log_entry = json.loads(captured.out.strip())

    assert log_entry["event"] == "test message"
    assert log_entry["key"] == "value"
    assert log_entry["level"] == "info"


# Custom Processor Tests


def test_custom_processors_applied_in_order(capsys):
    """Test that custom processors are applied in order."""

    def add_first(logger, method_name, event_dict):
        event_dict["order"] = ["first"]
        return event_dict

    def add_second(logger, method_name, event_dict):
        event_dict["order"].append("second")
        return event_dict

    configure_logging(
        formatter=FormatterType.JSON,
        processors=[add_first, add_second],
    )

    logger = structlog.get_logger()
    logger.info("order test")

    captured = capsys.readouterr()
    log_entry = json.loads(captured.err.strip())

    assert log_entry["order"] == ["first", "second"]


# Context Variables Tests


def test_merge_contextvars_includes_bound_context(capsys):
    """Test that bound context variables appear in log output."""
    configure_logging(formatter=FormatterType.JSON)

    structlog.contextvars.bind_contextvars(
        request_id="req-123",
        user_id="user-456",
    )

    logger = structlog.get_logger()
    logger.info("context test")

    captured = capsys.readouterr()
    log_entry = json.loads(captured.err.strip())

    assert log_entry["request_id"] == "req-123"
    assert log_entry["user_id"] == "user-456"

    structlog.contextvars.clear_contextvars()


# GCP Formatter Tests


def test_gcp_formatter_transforms_trace_fields(capsys):
    """Test that GCP formatter properly transforms trace context fields."""
    configure_logging(formatter=GCPFormatter(project_id="test-project"))

    structlog.contextvars.bind_contextvars(
        trace_id="abc123def456",
        span_id="span789",
    )

    logger = structlog.get_logger()
    logger.info("gcp test")

    captured = capsys.readouterr()
    log_entry = json.loads(captured.err.strip())

    assert log_entry["logging.googleapis.com/trace"] == "projects/test-project/traces/abc123def456"
    assert log_entry["logging.googleapis.com/spanId"] == "span789"
    assert "trace_id" not in log_entry
    assert "span_id" not in log_entry

    structlog.contextvars.clear_contextvars()


def test_gcp_formatter_with_env_project_id(monkeypatch):
    """Test GCPFormatter using GOOGLE_CLOUD_PROJECT environment variable."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "env-project")

    formatter = GCPFormatter()
    processors = formatter.get_processors()

    event_dict = {
        "trace_id": "abc123",
        "span_id": "def456",
        "event": "test",
    }

    result = processors[0](None, None, event_dict.copy())

    assert result["logging.googleapis.com/trace"] == "projects/env-project/traces/abc123"


def test_gcp_formatter_without_project_id(caplog):
    """Test GCPFormatter behavior when no project_id is available."""
    if "GOOGLE_CLOUD_PROJECT" in os.environ:
        del os.environ["GOOGLE_CLOUD_PROJECT"]

    # Should warn at creation time
    with caplog.at_level(logging.WARNING):
        formatter = GCPFormatter()

    assert "No project_id provided" in caplog.text

    # Should skip trace field but include span_id
    processors = formatter.get_processors()
    event_dict = {"trace_id": "abc123", "span_id": "def456", "event": "test"}
    result = processors[0](None, None, event_dict.copy())

    assert "logging.googleapis.com/trace" not in result
    assert result["logging.googleapis.com/spanId"] == "def456"
    assert "trace_id" not in result
    assert "span_id" not in result


def test_gcp_formatter_missing_trace_context():
    """Test GCPFormatter when trace context is missing or partial."""
    formatter = GCPFormatter(project_id="test-project")
    processors = formatter.get_processors()

    # No trace context at all
    event_dict = {"event": "test message", "key": "value"}
    result = processors[0](None, None, event_dict.copy())

    assert "logging.googleapis.com/trace" not in result
    assert "logging.googleapis.com/spanId" not in result
    assert result["event"] == "test message"

    # Only span_id (no trace_id)
    event_dict = {"span_id": "def456", "event": "test"}
    result = processors[0](None, None, event_dict.copy())

    assert "logging.googleapis.com/trace" not in result
    assert result["logging.googleapis.com/spanId"] == "def456"


# Reconfiguration Tests


def test_reconfiguration_changes_output_format(capsys):
    """Test that reconfiguring changes the output format."""
    # First configure with JSON
    configure_logging(formatter=FormatterType.JSON)
    logger = structlog.get_logger()
    logger.info("json output")

    captured1 = capsys.readouterr()
    json.loads(captured1.err.strip())  # Should be valid JSON

    # Reconfigure with console
    configure_logging(formatter=FormatterType.CONSOLE)
    logger = structlog.get_logger()
    logger.info("console output")

    captured2 = capsys.readouterr()

    # Should NOT be valid JSON anymore
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured2.err.strip())
