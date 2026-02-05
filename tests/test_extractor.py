import pytest

from asgi_structlog_otel.extractor import extract_from_traceparent, extract_otel


def test_extract_from_traceparent_valid():
    """Test extraction from a valid traceparent header."""
    scope = {
        "headers": [
            (b"traceparent", b"00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"),
        ]
    }
    result = extract_from_traceparent(scope)

    assert result == {
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
        "span_id": "b7ad6b7169203331",
    }


@pytest.mark.parametrize("scope", [
    {"headers": []},
    {"headers": [(b"other", b"value")]},
    {"type": "http"},  # no headers key
])
def test_extract_from_traceparent_missing_returns_empty(scope):
    """Test returns empty dict when traceparent is missing."""
    assert extract_from_traceparent(scope) == {}


@pytest.mark.parametrize("traceparent", [
    b"",  # empty
    b"00-0af765-b7ad6b7169203331-01",  # trace_id too short
    b"invalid-format",  # completely wrong
    b"ff-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",  # version ff
    b"00-00000000000000000000000000000000-b7ad6b7169203331-01",  # all-zero trace_id
    b"00-0af7651916cd43dd8448eb211c80319c-0000000000000000-01",  # all-zero span_id
])
def test_extract_from_traceparent_invalid_returns_empty(traceparent):
    """Test returns empty dict for invalid traceparent values."""
    scope = {"headers": [(b"traceparent", traceparent)]}
    assert extract_from_traceparent(scope) == {}


def test_extract_from_traceparent_normalizes_to_lowercase():
    """Test that uppercase hex is normalized to lowercase."""
    scope = {
        "headers": [
            (b"traceparent", b"00-0AF7651916CD43DD8448EB211C80319C-B7AD6B7169203331-01"),
        ]
    }
    result = extract_from_traceparent(scope)

    assert result["trace_id"] == "0af7651916cd43dd8448eb211c80319c"
    assert result["span_id"] == "b7ad6b7169203331"


def test_extract_otel_with_active_span(tracer):
    """Test extraction when there's an active span."""
    with tracer.start_as_current_span("test-span"):
        result = extract_otel({})

    assert len(result["trace_id"]) == 32
    assert len(result["span_id"]) == 16


def test_extract_otel_without_active_span():
    """Test returns empty dict when there's no active span."""
    assert extract_otel({}) == {}
