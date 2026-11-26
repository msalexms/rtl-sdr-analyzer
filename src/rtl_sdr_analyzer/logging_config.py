"""Single entry-point for structured logging configuration."""

import logging
import logging.config

import structlog
import structlog.stdlib

DEFAULT_SHARED_PROCESSORS: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.stdlib.ExtraAdder(),
]


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    *,
    force: bool = False,
) -> None:
    """Configure structured logging once at application startup."""
    if logging.root.handlers and not force:
        return

    normalized_level = level.upper()

    structlog.configure(
        processors=[
            *DEFAULT_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter: str = "json" if json_format else "console"

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
                    "level": normalized_level,
                },
            },
            "loggers": {
                "rtl_sdr_analyzer": {
                    "handlers": ["default"],
                    "level": normalized_level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "level": normalized_level,
                },
                "uvicorn.access": {
                    "level": "WARNING",
                },
            },
            "root": {
                "handlers": ["default"],
                "level": normalized_level,
            },
        }
    )
