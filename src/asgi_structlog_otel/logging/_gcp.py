"""Internal GCP Cloud Logging utilities.

This module provides processors for transforming OpenTelemetry trace context
into Google Cloud Logging format.
"""

from structlog.typing import EventDict, Processor, WrappedLogger


def _add_gcp_trace_fields(
    project_id: str | None = None,
) -> Processor:
    """Create processor that transforms trace context to GCP format.

    Transforms trace context fields into Google Cloud Logging format:
    - trace_id → logging.googleapis.com/trace (with project prefix)
    - span_id → logging.googleapis.com/spanId

    If no project_id is provided, the trace field will be omitted but
    span_id will still be included.

    Args:
        project_id: GCP project ID, already resolved by GCPFormatter.
    """
    resolved_project_id = project_id

    def processor(
        logger: WrappedLogger,
        method_name: str,
        event_dict: EventDict,
    ) -> EventDict:
        # Extract OpenTelemetry trace context
        trace_id = event_dict.pop("trace_id", None)
        span_id = event_dict.pop("span_id", None)

        if trace_id and resolved_project_id:
            # Format: projects/PROJECT_ID/traces/TRACE_ID
            event_dict["logging.googleapis.com/trace"] = (
                f"projects/{resolved_project_id}/traces/{trace_id}"
            )

        if span_id:
            event_dict["logging.googleapis.com/spanId"] = span_id

        return event_dict

    return processor
