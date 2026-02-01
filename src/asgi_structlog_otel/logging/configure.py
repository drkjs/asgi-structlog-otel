"""Structlog configuration with OpenTelemetry trace correlation."""

import logging
import sys
from enum import StrEnum
from typing import Callable

import structlog
from structlog.typing import Processor, WrappedLogger

from asgi_structlog_otel.logging.formatter import (
    ConsoleFormatter,
    Formatter,
    JSONFormatter,
)


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
        to pick up trace context from TraceContextMiddleware. Custom processors
        are inserted before the final wrap_for_formatter processor.
    """
    formatter_instance = _resolve_formatter(formatter)
    base_processors = _build_base_processors()

    if processors:
        # Insert custom processors before wrap_for_formatter (last in chain)
        base_processors = base_processors[:-1] + processors + [base_processors[-1]]

    if configure_stdlib:
        _configure_stdlib_logging(
            formatter_instance=formatter_instance,
            base_processors=base_processors,
            level=level,
        )
        if logger_factory is None:
            logger_factory = structlog.stdlib.LoggerFactory()
    else:
        if logger_factory is None:
            logger_factory = structlog.PrintLoggerFactory()

    structlog.configure(
        processors=base_processors,
        logger_factory=logger_factory,
        cache_logger_on_first_use=True,
    )


def _resolve_formatter(
    formatter: Formatter | FormatterType | None,
) -> Formatter | None:
    """Resolve formatter specification to a formatter instance.

    Args:
        formatter: FormatterType enum, Formatter instance, or None.

    Returns:
        Formatter instance or None.
    """
    match formatter:
        case FormatterType.AUTO:
            return ConsoleFormatter() if sys.stderr.isatty() else JSONFormatter()
        case FormatterType.JSON:
            return JSONFormatter()
        case FormatterType.CONSOLE:
            return ConsoleFormatter()
        case None:
            return None
        case _:
            return formatter


def _build_base_processors() -> list[Processor]:
    """Build the base processor chain.

    Returns:
        List of core processors that are always included.

    Note:
        merge_contextvars MUST be first in the chain to pick up trace_id and
        span_id that TraceContextMiddleware binds to contextvars. Without this,
        trace correlation will not work.

        wrap_for_formatter MUST be last for stdlib logging integration to work
        correctly with ProcessorFormatter.
    """
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]


def _configure_stdlib_logging(
    formatter_instance: Formatter | None,
    base_processors: list[Processor],
    level: int,
) -> None:
    """Configure stdlib logging to forward to structlog.

    Args:
        formatter_instance: Formatter to use for output. If None, defaults
            to JSON formatter.
        base_processors: Base processor chain.
        level: Logging level to set on root logger.
    """
    if formatter_instance:
        formatter_processors = formatter_instance.get_processors()
    else:
        formatter_processors = [structlog.processors.JSONRenderer()]

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
