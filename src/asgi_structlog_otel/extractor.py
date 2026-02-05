import re
from typing import Any, Protocol

from opentelemetry import trace
from opentelemetry.trace.span import INVALID_SPAN

# W3C Trace Context traceparent header format:
# {version}-{trace_id}-{parent_id}-{flags}
# Example: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01
_TRACEPARENT_PATTERN = re.compile(
    r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)


class Extractor(Protocol):
    def __call__(self, scope: dict[str, Any]) -> dict[str, Any]:
        ...


def extract_otel(scope: dict[str, Any]) -> dict[str, Any]:

    span = trace.get_current_span()

    if span is INVALID_SPAN or not span.is_recording():
        return {}

    span_ctx = span.get_span_context()

    return {
        "trace_id": trace.format_trace_id(span_ctx.trace_id),
        "span_id": trace.format_span_id(span_ctx.span_id),
    }


def extract_from_traceparent(scope: dict[str, Any]) -> dict[str, Any]:
    """Extract trace context directly from the W3C traceparent header.

    Unlike extract_otel, this reads the header directly from the ASGI scope
    without requiring OpenTelemetry SDK or instrumentation packages. This means
    no TracerProvider configuration, no instrumentation middleware, and no
    span creation - just header parsing.

    Trade-offs vs extract_otel:
    + No SDK or instrumentation dependencies required
    + No configuration needed
    - Your service won't appear in trace visualizations (no spans created)
    - Cannot create spans for internal operations (DB calls, HTTP clients)
    - Cannot propagate trace context to downstream services
    - Sampling decisions in the header are ignored

    W3C Trace Context format: {version}-{trace_id}-{parent_id}-{flags}
    Example: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01

    Args:
        scope: ASGI scope dictionary

    Returns:
        Dictionary with trace_id and span_id if valid traceparent found,
        empty dictionary otherwise.
    """
    headers = dict(scope.get("headers", []))
    traceparent = headers.get(b"traceparent", b"").decode()

    if not traceparent:
        return {}

    match = _TRACEPARENT_PATTERN.match(traceparent.lower())
    if not match:
        return {}

    version, trace_id, span_id, flags = match.groups()

    # Version 255 (ff) is invalid per spec
    if version == "ff":
        return {}

    # All zeros trace_id or span_id are invalid
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return {}

    return {
        "trace_id": trace_id,
        "span_id": span_id,
    }