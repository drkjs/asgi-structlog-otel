import re
from typing import Any, Protocol

# W3C Trace Context traceparent header format:
# {version}-{trace_id}-{parent_id}-{flags}
# Example: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01
_TRACEPARENT_PATTERN = re.compile(
    r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)

# GCP X-Cloud-Trace-Context header format:
# {trace_id}/{span_id};o={sampled}
# Example: 105445aa7843bc8bf206b12000100000/1;o=1
_GCP_TRACE_PATTERN = re.compile(
    r"^([0-9a-f]{32})/(\d+)(?:;o=([01]))?$"
)


class Extractor(Protocol):
    """Protocol for trace context extractors.

    Extractors are called by TraceContextMiddleware to build trace context
    from ASGI requests. The context parameter is always provided by the
    middleware. Its usage is optional, but it can be used to check what
    previous extractors have already added and only fill in missing keys.

    Returns:
        dict[str, Any]: Key-value pairs to merge into the trace context.
            Return empty dict if nothing could be extracted.
    """

    def __call__(self, scope: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        ...


def extract_otel(scope: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Extract trace context from the current OpenTelemetry span.

    Requires opentelemetry-api to be installed. Install with:
        pip install asgi-structlog-otel[otel]
    """
    try:
        from opentelemetry import trace
        from opentelemetry.trace.span import INVALID_SPAN
    except ImportError:
        raise ImportError(
            "opentelemetry-api is required for extract_otel. "
            "Install it with: pip install asgi-structlog-otel[otel]"
        )

    span = trace.get_current_span()

    if span is INVALID_SPAN or not span.is_recording():
        return {}

    span_ctx = span.get_span_context()

    return {
        "trace_id": trace.format_trace_id(span_ctx.trace_id),
        "span_id": trace.format_span_id(span_ctx.span_id),
    }


def extract_from_traceparent(scope: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Extract trace context directly from the W3C traceparent header.

    Unlike extract_otel (which reads from the active OpenTelemetry span),
    this extracts trace_id by parsing the incoming header directly.

    Trade-offs vs extract_otel:
    + Works without initializing OpenTelemetry
    + No configuration needed
    - Won't create spans or instrument your application
    - Cannot propagate context to downstream services automatically
    - Sampling decisions in the header are ignored

    W3C Trace Context format: {version}-{trace_id}-{parent_id}-{flags}
    Example: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01

    Args:
        scope: ASGI scope dictionary

    Returns:
        Dictionary with trace_id if valid traceparent found,
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
    }


def extract_gcp_trace_header(scope: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Extract trace_id from GCP's X-Cloud-Trace-Context header.

    This is a fallback extractor that only fills in trace_id if it isn't
    already present in the context. Use it after extract_otel or
    extract_from_traceparent to handle cases where GCP injects its proprietary
    header but OpenTelemetry instrumentation isn't set up.

    GCP header format: {trace_id}/{span_id};o={sampled}
    Example: 105445aa7843bc8bf206b12000100000/1;o=1

    Args:
        scope: ASGI scope dictionary
        context: Accumulated context from previous extractors

    Returns:
        dict[str, Any]: trace_id if missing from context,
            plus gcp_trace_sampled if present in header.
    """
    if "trace_id" in context:
        return {}

    headers = dict(scope.get("headers", []))
    gcp_trace = headers.get(b"x-cloud-trace-context", b"").decode()

    if not gcp_trace:
        return {}

    match = _GCP_TRACE_PATTERN.match(gcp_trace.lower())
    if not match:
        return {}

    trace_id, span_id_decimal, sampled = match.groups()

    result: dict[str, Any] = {}
    result["trace_id"] = trace_id

    # Always add sampled flag if present
    if sampled is not None:
        result["gcp_trace_sampled"] = sampled == "1"

    return result