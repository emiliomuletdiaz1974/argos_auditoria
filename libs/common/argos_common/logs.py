"""Structured JSON logging with mandatory fields (ARG-001; consumed by Loki in ARG-093)."""

import json
import logging
import re
import sys
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any, TextIO

OPTIONAL_FIELDS = ("journal_seq", "trace_id", "campaign_id")
_MARKER = "_argos_handler"
_COMPONENT = re.compile(r"^ARG-\d{3}$")


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="microseconds"
            ),
            "level": record.levelname,
            "service": self.service,
            "component": getattr(record, "component", "no-component"),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in OPTIONAL_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class _ArgosAdapter(logging.LoggerAdapter[logging.Logger]):
    """Merge the fixed component with each call's `extra` (3.12 would discard it)."""

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        kwargs["extra"] = {**(self.extra or {}), **kwargs.get("extra", {})}
        return msg, kwargs


def configure_logging(service: str, level: str = "INFO", stream: TextIO | None = None) -> None:
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _MARKER, False)]:
        root.removeHandler(handler)
    new_handler = logging.StreamHandler(stream or sys.stdout)
    new_handler.setFormatter(JsonFormatter(service))
    setattr(new_handler, _MARKER, True)
    root.addHandler(new_handler)
    root.setLevel(str(level).upper())


def get_logger(name: str, component: str) -> logging.LoggerAdapter[logging.Logger]:
    if not _COMPONENT.match(component):
        raise ValueError(f"component must match ARG-NNN, got {component!r}")
    return _ArgosAdapter(logging.getLogger(name), {"component": component})
