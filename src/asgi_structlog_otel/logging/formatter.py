"""Pluggable log formatters for structlog.

This module provides the Formatter protocol and built-in formatters for
different output formats (JSON, Console, GCP Cloud Logging).
"""

import logging
import os
from typing import Any, Callable, Protocol

import structlog
from structlog.typing import Processor

logger = logging.getLogger(__name__)


class Formatter(Protocol):
    """Protocol for pluggable log formatters.

    Formatters are responsible for creating the final processor chain
    that transforms structured log events into their output format.

    Example:
        >>> class MyFormatter:
        ...     def get_processors(self):
        ...         return [structlog.processors.JSONRenderer()]
        >>> configure_logging(formatter=MyFormatter())
    """

    def get_processors(self) -> list[Processor]:
        """Return the processor chain for this formatter.

        Returns:
            List of structlog processors ending with a renderer.
        """
        ...


class JSONFormatter:
    """JSON formatter for machine-readable logs.

    Produces structured JSON output suitable for log aggregation systems
    and production environments.

    Args:
        sort_keys: If True, sort dictionary keys in output.
        indent: Number of spaces for indentation. None for compact output.

    Example:
        >>> configure_logging(formatter=JSONFormatter(indent=2))
    """

    def __init__(
        self,
        *,
        sort_keys: bool = False,
        indent: int | None = None,
    ):
        self.sort_keys = sort_keys
        self.indent = indent

    def get_processors(self) -> list[Processor]:
        """Return JSON renderer processor."""
        return [
            structlog.processors.JSONRenderer(
                sort_keys=self.sort_keys,
                indent=self.indent,
            )
        ]


class ConsoleFormatter:
    """Human-friendly console formatter with colors.

    Produces pretty-printed console output suitable for development
    environments and terminal viewing.

    Args:
        colors: If True, include ANSI color codes in output.
        exception_formatter: Custom exception formatter callable.

    Example:
        >>> configure_logging(formatter=ConsoleFormatter())
    """

    def __init__(
        self,
        *,
        colors: bool = True,
        exception_formatter: Callable[..., Any] | None = None,
    ):
        self.colors = colors
        self.exception_formatter = exception_formatter

    def get_processors(self) -> list[Processor]:
        """Return console renderer processor."""
        return [
            structlog.dev.ConsoleRenderer(
                colors=self.colors,
                exception_formatter=self.exception_formatter,
            )
        ]


class GCPFormatter:
    """Google Cloud Logging formatter with trace correlation.

    Transforms OpenTelemetry trace context into GCP-specific fields for
    proper trace correlation in Google Cloud Logging:
    - trace_id → logging.googleapis.com/trace (with project prefix)
    - span_id → logging.googleapis.com/spanId

    **Important**: Trace correlation requires a GCP project ID. If no project_id
    is provided (via constructor or GOOGLE_CLOUD_PROJECT environment variable),
    the trace field will be omitted from logs. The span_id field will still be
    included if available, but full trace correlation in GCP Console will not work.

    For proper trace correlation, ensure project_id is set via:
    - Constructor: GCPFormatter(project_id="my-project")
    - Environment: export GOOGLE_CLOUD_PROJECT="my-project"

    Args:
        project_id: GCP project ID. If None, attempts to read from
            GOOGLE_CLOUD_PROJECT environment variable. If still unavailable,
            the trace field will be omitted (span_id will still be included).
        sort_keys: If True, sort dictionary keys in JSON output.

    Example:
        >>> # With explicit project ID
        >>> configure_logging(
        ...     formatter=GCPFormatter(project_id="my-project")
        ... )

        >>> # Using environment variable
        >>> import os
        >>> os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        >>> configure_logging(formatter=GCPFormatter())
    """

    def __init__(
        self,
        *,
        project_id: str | None = None,
        sort_keys: bool = False,
    ):
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.sort_keys = sort_keys

        # Warn at configuration time if project_id is missing
        if not self.project_id:
            logger.warning(
                "GCPFormatter: No project_id provided. Trace correlation will not work. "
                "Set via constructor or GOOGLE_CLOUD_PROJECT environment variable."
            )

    def get_processors(self) -> list[Processor]:
        """Return GCP field transformation and JSON renderer processors."""
        from asgi_structlog_otel.logging._gcp import add_gcp_trace_fields

        return [
            add_gcp_trace_fields(project_id=self.project_id),
            structlog.processors.JSONRenderer(sort_keys=self.sort_keys),
        ]
