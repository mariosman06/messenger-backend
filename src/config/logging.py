"""Logging configuration, context filters, and formatters."""

import json
import logging
import logging.config
import sys
from contextvars import ContextVar

from src.config.settings import get_settings

settings = get_settings()

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class LogContextFilter(logging.Filter):
    """Injects formatted request tag into log records only when an active request exists."""

    def filter(self, record: logging.LogRecord) -> bool:
        req_id = request_id_var.get()
        if req_id and req_id != "system":
            record.req_tag = f" [req:{req_id}]"
            record.request_id = req_id
        else:
            record.req_tag = ""
            record.request_id = None
        return True


class SafeStandardFormatter(logging.Formatter):
    """Standard formatter that safely defaults missing context attributes."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "req_tag"):
            record.req_tag = ""
        return super().format(record)


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON strings for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "pid": record.process,
            "logger": record.name,
            "message": record.getMessage(),
        }

        req_id = getattr(record, "request_id", None) or request_id_var.get()
        if req_id and req_id != "system":
            data["request_id"] = req_id

        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data)


def get_logging_config() -> dict:
    """Generates dictConfig configuration with standard text or JSON formatting."""
    use_json = getattr(settings.logging, "json_format", False)

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "context": {"()": LogContextFilter},
        },
        "formatters": {
            "standard": {
                "()": SafeStandardFormatter,
                "format": "%(asctime)s [%(levelname)s] [pid:%(process)d] [%(name)s]%(req_tag)s %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "()": JSONFormatter,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "json" if use_json else "standard",
                "filters": ["context"],
            },
        },
        "root": {
            "level": settings.logging.level.upper(),
            "handlers": ["console"],
        },
        "loggers": {
            "uvicorn.access": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False,
            },
            "uvicorn.error": {
                "level": settings.logging.level.upper(),
                "handlers": ["console"],
                "propagate": False,
            },
        },
    }


def setup_logging() -> None:
    """Applies global logging setup."""
    logging.config.dictConfig(get_logging_config())
