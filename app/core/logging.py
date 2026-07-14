from __future__ import annotations

import json
import logging
from typing import Any

from app.core.security import redact_sensitive_values


class JsonFormatter(logging.Formatter):
    def __init__(self, *, sensitive_values: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.sensitive_values = sensitive_values

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(
            redact_sensitive_values(payload, sensitive_values=self.sensitive_values),
            ensure_ascii=False,
        )


class RedactingTextFormatter(logging.Formatter):
    def __init__(self, *, sensitive_values: tuple[str, ...] = ()) -> None:
        super().__init__("%(levelname)s %(name)s %(message)s")
        self.sensitive_values = sensitive_values

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return str(
            redact_sensitive_values(rendered, sensitive_values=self.sensitive_values)
        )


def configure_logging(
    level: str = "INFO",
    log_format: str = "json",
    *,
    sensitive_values: tuple[str, ...] = (),
) -> None:
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter(sensitive_values=sensitive_values))
    else:
        handler.setFormatter(RedactingTextFormatter(sensitive_values=sensitive_values))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
