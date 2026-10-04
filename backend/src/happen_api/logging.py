"""JSON logs with secret-bearing fields removed before output."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

_SECRET_FIELD = re.compile(r"(key|token|secret|authorization|cookie)", re.IGNORECASE)
_LOGGER_NAME = "happen"


class SecretRedactionFilter(logging.Filter):
    """Replace values whose field names look like credentials."""

    def filter(self, record: logging.LogRecord) -> bool:
        for name, value in list(record.__dict__.items()):
            if _SECRET_FIELD.search(name):
                setattr(record, name, "[redacted]")
                continue
            if isinstance(value, dict):
                setattr(record, name, _redact_mapping(value))
        return True


def _redact_mapping(value: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, item in value.items():
        if _SECRET_FIELD.search(str(key)):
            redacted[key] = "[redacted]"
        elif isinstance(item, dict):
            redacted[key] = _redact_mapping(item)
        else:
            redacted[key] = item
    return redacted


class JsonFormatter(logging.Formatter):
    """One JSON object per log line, limited to operational fields."""

    _FIELDS = (
        "request_id",
        "endpoint",
        "status_code",
        "duration_ms",
        "error_code",
        "exception_type",
        "mode",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        }
        for name in self._FIELDS:
            if hasattr(record, name):
                payload[name] = getattr(record, name)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(level: str) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level.upper())
    if not any(isinstance(item, JsonFormatter) for item in _formatters(logger)):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler.addFilter(SecretRedactionFilter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def _formatters(logger: logging.Logger) -> list[logging.Formatter]:
    return [handler.formatter for handler in logger.handlers if handler.formatter is not None]


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)
