"""Single entry-point for structured logging configuration."""

import logging
import logging.config

import structlog


DEFAULT_SHARED_PROCESSORS: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.stdlib.ExtraAdder(),
]


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
) -> None:
    """Configure logging once at application startup.

    Must be called **exactly once** before any module creates loggers.
    Modules should only use ``logging.getLogger(__name__)`` — never
    ``logging.basicConfig()``.

    Args:
        level: Root log level (DEBUG, INFO, WARNING, ERROR).
        json_format: Emit JSON logs instead of plain text.
    """
    # Prevent duplicate configuration
    if logging.root.handlers:
        return

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            timestamper,
            structlog.stdlib.ExtraAdder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter: str
    if json_format:
        formatter = "json"
    else:
        formatter = "console"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processor": structlog.processors.JSONRenderer(),
                    "foreign_pre_chain": DEFAULT_SHARED_PROCESSORS,
                },
                "console": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processor": structlog.dev.ConsoleRenderer(colors=True),
                    "foreign_pre_chain": DEFAULT_SHARED_PROCESSORS,
                },
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": formatter,
                    "level": level,
                },
            },
            "loggers": {
                "rtl_sdr_analyzer": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
            },
            "root": {
                "handlers": ["default"],
                "level": level,
            },
        }
    )
