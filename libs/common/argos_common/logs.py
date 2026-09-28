"""Structured JSON logging with mandatory fields (ARG-001), sent to Loki by each service (ARG-093).

With `ARGOS_LOKI_URL` set, every service also pushes the same JSON lines to Loki itself: no
collector reads the logs of the containers, so no container needs the Docker socket (DP-16). The
push never blocks the service: a full queue or an unreachable Loki drops records and counts them.
"""

import collections
import json
import logging
import os
import re
import sys
import threading
import urllib.request
from collections.abc import Callable, MutableMapping
from datetime import UTC, datetime
from typing import Any, TextIO

OPTIONAL_FIELDS = ("journal_seq", "trace_id", "campaign_id")
# What every LogRecord has: anything else on a record came in `extra`, and is context the call
# wanted in the line (quality review QA-007: all but the three optional fields were dropped).
_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
    "component",
}
_MARKER = "_argos_handler"
LOKI_URL_VARIABLE = "ARGOS_LOKI_URL"
Sender = Callable[[dict[str, Any]], None]
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
        for field, value in record.__dict__.items():
            if field in _RECORD_FIELDS or field in OPTIONAL_FIELDS or field.startswith("_"):
                continue
            # A mandatory field is never overwritten by the call: its value keeps its own name.
            entry[f"extra_{field}" if field in entry else field] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def http_sender(url: str, timeout: float = 2.0) -> Sender:
    """POST a push payload to Loki; any failure is the caller's to count."""

    def send(payload: dict[str, Any]) -> None:
        request = urllib.request.Request(  # noqa: S310 - the configured Loki
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            response.read()

    return send


class LokiHandler(logging.Handler):
    """Batches the JSON lines of the service to the push API of Loki, never blocking it.

    Two labels only, `service` and `level`, to keep the cardinality low; everything else (the
    component, the journal sequence, the campaign) travels inside the line. The queue is bounded:
    when it is full, or when a batch cannot be sent, the records are dropped and counted in
    `dropped`, and the service goes on.
    """

    def __init__(
        self,
        service: str,
        url: str | None = None,
        *,
        sender: Sender | None = None,
        batch_size: int = 200,
        flush_seconds: float = 2.0,
        max_queue: int = 10_000,
    ) -> None:
        super().__init__()
        if sender is None and url is None:
            raise ValueError("a Loki handler needs a URL or a sender")
        self.setFormatter(JsonFormatter(service))
        self.service = service
        self.dropped = 0
        self._send = sender if sender is not None else http_sender(str(url))
        self._batch_size = batch_size
        self._flush_seconds = flush_seconds
        self._queue: collections.deque[tuple[int, str, str]] = collections.deque()
        self._max_queue = max_queue
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="loki-push", daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # a record that does not format is the logging module's to report
            self.handleError(record)
            return
        with self._lock:
            if len(self._queue) >= self._max_queue:
                self.dropped += 1
                return
            self._queue.append((int(record.created * 1e9), record.levelname, line))
            full = len(self._queue) >= self._batch_size
        if full:
            self._wake.set()

    def _take(self) -> list[tuple[int, str, str]]:
        with self._lock:
            batch = [self._queue.popleft() for _ in range(min(self._batch_size, len(self._queue)))]
        return batch

    def _push(self, batch: list[tuple[int, str, str]]) -> None:
        streams: dict[str, list[list[str]]] = {}
        for nanos, level, line in batch:
            streams.setdefault(level, []).append([str(nanos), line])
        payload = {
            "streams": [
                {"stream": {"service": self.service, "level": level}, "values": values}
                for level, values in streams.items()
            ]
        }
        try:
            self._send(payload)
        except Exception:  # Loki down or refusing: the lines are lost, the service is not
            with self._lock:
                self.dropped += len(batch)

    def _drain(self) -> None:
        while batch := self._take():
            self._push(batch)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self._flush_seconds)
            self._wake.clear()
            self._drain()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=5)
        self._drain()
        super().close()


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
        if isinstance(handler, LokiHandler):
            handler.close()
    new_handler = logging.StreamHandler(stream or sys.stdout)
    new_handler.setFormatter(JsonFormatter(service))
    setattr(new_handler, _MARKER, True)
    root.addHandler(new_handler)
    loki_url = os.environ.get(LOKI_URL_VARIABLE)
    if loki_url:
        loki = LokiHandler(service, loki_url)
        setattr(loki, _MARKER, True)
        root.addHandler(loki)
    root.setLevel(str(level).upper())


def loki_dropped() -> int:
    """Records this process dropped instead of sending them to Loki (0 without Loki)."""
    return sum(h.dropped for h in logging.getLogger().handlers if isinstance(h, LokiHandler))


def get_logger(name: str, component: str) -> logging.LoggerAdapter[logging.Logger]:
    if not _COMPONENT.match(component):
        raise ValueError(f"component must match ARG-NNN, got {component!r}")
    return _ArgosAdapter(logging.getLogger(name), {"component": component})
