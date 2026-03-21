"""Internal GCP Cloud Logging utilities.

This module provides processors for transforming OpenTelemetry trace context
into Google Cloud Logging format.
"""

import os

from structlog.typing import EventDict, Processor, WrappedLogger


def add_gcp_trace_fields(
    project_id: str | None = None,
) -> Processor:
    """Create processor that transforms trace context to GCP format.

    Transforms OpenTelemetry trace context fields into Google Cloud Logging
    format for proper trace correlation:
    - trace_id → logging.googleapis.com/trace (with project prefix)
    - span_id → logging.googleapis.com/spanId

    If no project_id is available, the trace field will be omitted but
    span_id will still be included.

    Args:
        project_id: GCP project ID. If None, attempts to read from
            GOOGLE_CLOUD_PROJECT environment variable.

    Returns:
        Processor function that transforms trace fields.

    Example:
        >>> processor = add_gcp_trace_fields(project_id="my-project")
        >>> event_dict = processor(None, None, {
        ...     "trace_id": "0af7651916cd43dd8448eb211c80319c",
        ...     "span_id": "b7ad6b7169203331",
        ...     "event": "test",
        ... })
        >>> event_dict["logging.googleapis.com/trace"]
        'projects/my-project/traces/0af7651916cd43dd8448eb211c80319c'
    """
    # Resolve project_id once at processor creation time
    resolved_project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")

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
