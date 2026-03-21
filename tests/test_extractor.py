import pytest

from asgi_structlog_otel.extractor import (
    extract_from_traceparent,
    extract_gcp_trace_header,
    extract_otel,
)


def test_extract_from_traceparent_valid():
    """Test extraction from a valid traceparent header."""
    scope = {
        "headers": [
            (b"traceparent", b"00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"),
        ]
    }
    result = extract_from_traceparent(scope, {})

    assert result == {
        "trace_id": "0af7651916cd43dd8448eb211c80319c",
    }


@pytest.mark.parametrize("scope", [
    {"headers": []},
    {"headers": [(b"other", b"value")]},
    {"type": "http"},  # no headers key
])
def test_extract_from_traceparent_missing_returns_empty(scope):
    """Test returns empty dict when traceparent is missing."""
    assert extract_from_traceparent(scope, {}) == {}


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
    assert extract_from_traceparent(scope, {}) == {}


def test_extract_from_traceparent_normalizes_to_lowercase():
    """Test that uppercase hex is normalized to lowercase."""
    scope = {
        "headers": [
            (b"traceparent", b"00-0AF7651916CD43DD8448EB211C80319C-B7AD6B7169203331-01"),
        ]
    }
    result = extract_from_traceparent(scope, {})

    assert result["trace_id"] == "0af7651916cd43dd8448eb211c80319c"


def test_extract_otel_with_active_span(tracer):
    """Test extraction when there's an active span."""
    with tracer.start_as_current_span("test-span"):
        result = extract_otel({}, {})

    assert len(result["trace_id"]) == 32
    assert len(result["span_id"]) == 16


def test_extract_otel_without_active_span():
    """Test returns empty dict when there's no active span."""
    assert extract_otel({}, {}) == {}


@pytest.mark.parametrize("header,expected_sampled", [
    (b"105445aa7843bc8bf206b12000100000/123;o=1", True),
    (b"105445aa7843bc8bf206b12000100000/456;o=0", False),
    (b"105445aa7843bc8bf206b12000100000/789", None),
])
def test_extract_gcp_trace_header_valid(header, expected_sampled):
    """Test extraction from X-Cloud-Trace-Context header."""
    scope = {"headers": [(b"x-cloud-trace-context", header)]}
    result = extract_gcp_trace_header(scope, {})

    assert result["trace_id"] == "105445aa7843bc8bf206b12000100000"
    if expected_sampled is None:
        assert "gcp_trace_sampled" not in result
    else:
        assert result["gcp_trace_sampled"] is expected_sampled


def test_extract_gcp_trace_header_fallback_behavior():
    """Test that GCP extractor only fills missing trace_id."""
    scope = {"headers": [(b"x-cloud-trace-context", b"105445aa7843bc8bf206b12000100000/123;o=1")]}

    # When trace_id exists, return empty
    assert extract_gcp_trace_header(scope, {"trace_id": "existing"}) == {}

    # When missing, fill it
    result = extract_gcp_trace_header(scope, {})
    assert result["trace_id"] == "105445aa7843bc8bf206b12000100000"


@pytest.mark.parametrize("header", [
    b"",  # empty
    b"invalid",  # wrong format
    b"not-32-chars/123;o=1",  # trace_id wrong length
])
def test_extract_gcp_trace_header_invalid_returns_empty(header):
    """Test returns empty dict for invalid header values."""
    scope = {"headers": [(b"x-cloud-trace-context", header)]}
    assert extract_gcp_trace_header(scope, {}) == {}
