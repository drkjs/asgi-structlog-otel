"""Structlog configuration with OpenTelemetry trace correlation."""

import logging
import sys
from enum import StrEnum
from typing import Callable

import structlog
from structlog.typing import Processor, WrappedLogger

from asgi_structlog_otel.logging.formatter import Formatter


class FormatterType(StrEnum):
    """Built-in formatter types for configure_logging.

    Attributes:
        AUTO: Auto-detect format based on TTY (console if terminal, JSON otherwise)
        JSON: JSON output for production environments
        CONSOLE: Human-friendly console output for development
    """

    AUTO = "auto"
    JSON = "json"
    CONSOLE = "console"


def configure_logging(
    *,
    formatter: Formatter | FormatterType = FormatterType.AUTO,
    level: int = logging.INFO,
    configure_stdlib: bool = True,
    processors: list[Processor] | None = None,
    logger_factory: Callable[..., WrappedLogger] | None = None,
) -> None:
    """Configure structlog with OpenTelemetry trace correlation.

    Sets up structlog to automatically include trace_id and span_id from
    OpenTelemetry spans in log output. Works seamlessly with
    TraceContextMiddleware to correlate logs with distributed traces.

    Args:
        formatter: Output formatter. Can be a FormatterType enum value,
            a custom Formatter instance, or None to skip configuration.
        level: Logging level (use logging.INFO, logging.DEBUG, etc.).
        configure_stdlib: If True, configure stdlib logging to forward
            to structlog. Recommended for comprehensive log capture from
            third-party libraries.
        processors: Additional custom processors to insert before formatter
            processors. Common processors (merge_contextvars, add_log_level,
            etc.) are added automatically.
        logger_factory: Custom logger factory. If None, uses appropriate
            factory based on configure_stdlib setting.

    Example:
        Basic setup with auto-detection:

        >>> from asgi_structlog_otel.logging import configure_logging
        >>> configure_logging()

        Explicit JSON format for production:

        >>> from asgi_structlog_otel.logging import FormatterType
        >>> configure_logging(formatter=FormatterType.JSON)

        Console format for development:

        >>> import logging
        >>> configure_logging(
        ...     formatter=FormatterType.CONSOLE,
        ...     level=logging.DEBUG
        ... )

        GCP Cloud Logging:

        >>> from asgi_structlog_otel.logging import GCPFormatter
        >>> configure_logging(
        ...     formatter=GCPFormatter(project_id="my-project")
        ... )

        Custom formatter:

        >>> class MyFormatter:
        ...     def get_processors(self):
        ...         return [structlog.processors.JSONRenderer(indent=2)]
        >>> configure_logging(formatter=MyFormatter())

    Note:
        The processor chain always includes structlog.contextvars.merge_contextvars
        to pick up trace context from TraceContextMiddleware.
    """
    formatter_processors = _resolve_formatter(formatter)
    base_processors = _build_base_processors()

    if processors:
        base_processors = base_processors + processors

    if configure_stdlib:
        # Add wrap_for_formatter for stdlib integration
        base_processors = base_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter
        ]
        _configure_stdlib_logging(
            formatter_processors=formatter_processors,
            base_processors=base_processors,
            level=level,
        )
        if logger_factory is None:
            logger_factory = structlog.stdlib.LoggerFactory()
    else:
        # Add formatter processors directly to the chain
        base_processors = base_processors + formatter_processors
        if logger_factory is None:
            logger_factory = structlog.PrintLoggerFactory()

    structlog.configure(
        processors=base_processors,
        logger_factory=logger_factory,
        cache_logger_on_first_use=True,
    )


def _resolve_formatter(
    formatter: Formatter | FormatterType,
) -> list[Processor]:
    """Resolve formatter specification to processors.

    Args:
        formatter: FormatterType enum or Formatter instance.

    Returns:
        List of processors for the formatter.
    """
    match formatter:
        case FormatterType.AUTO:
            if sys.stderr.isatty():
                return [structlog.dev.ConsoleRenderer()]
            return [structlog.processors.JSONRenderer()]
        case FormatterType.JSON:
            return [structlog.processors.JSONRenderer()]
        case FormatterType.CONSOLE:
            return [structlog.dev.ConsoleRenderer()]
        case _:
            return formatter.get_processors()


def _build_base_processors() -> list[Processor]:
    """Build the base processor chain.

    Returns:
        List of core processors that are always included.

    Note:
        merge_contextvars MUST be first in the chain to pick up trace_id and
        span_id that TraceContextMiddleware binds to contextvars. Without this,
        trace correlation will not work.
    """
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]


def _configure_stdlib_logging(
    formatter_processors: list[Processor],
    base_processors: list[Processor],
    level: int,
) -> None:
    """Configure stdlib logging to forward to structlog.

    Args:
        formatter_processors: Processors for formatting output.
        base_processors: Base processor chain.
        level: Logging level to set on root logger.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=formatter_processors,
            # Exclude wrap_for_formatter (last processor) from foreign_pre_chain
            # since it's only needed for structlog's own loggers, not stdlib
            foreign_pre_chain=base_processors[:-1],
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
