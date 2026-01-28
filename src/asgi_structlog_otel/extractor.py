from typing import Any, Protocol
from opentelemetry import trace
from opentelemetry.trace.span import INVALID_SPAN

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