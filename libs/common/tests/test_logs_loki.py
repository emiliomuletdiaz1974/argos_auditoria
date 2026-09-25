"""ARG-093 · the services send their own logs to Loki, without a collector (F10-05, DP-16).

The handler takes the same JSON line the service writes to its standard output and sends it in
batches to the push API of Loki, with two labels only (service and level). It never blocks the
service: a full queue or an unreachable Loki drops the records and counts them.
"""

import io
import json
import logging
import threading
from typing import Any

import pytest

from argos_common.logs import LokiHandler, configure_logging, get_logger


class _Sender:
    def __init__(self, fail: bool = False, gate: threading.Event | None = None) -> None:
        self.payloads: list[dict[str, Any]] = []
        self._fail = fail
        self._gate = gate

    def __call__(self, payload: dict[str, Any]) -> None:
        if self._gate is not None:
            self._gate.wait(5)
        if self._fail:
            raise OSError("loki unreachable")
        self.payloads.append(payload)


def _logger(handler: logging.Handler) -> logging.Logger:
    logger = logging.getLogger(f"test-loki-{id(handler)}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger


def _lines(sender: _Sender) -> list[tuple[dict[str, str], dict[str, Any]]]:
    return [
        (stream["stream"], json.loads(line))
        for payload in sender.payloads
        for stream in payload["streams"]
        for _, line in stream["values"]
    ]


def test_the_lines_go_in_batches_with_two_labels_only() -> None:
    sender = _Sender()
    handler = LokiHandler("argos-test", sender=sender, batch_size=10, flush_seconds=60)
    logger = _logger(handler)
    logger.info("first", extra={"component": "ARG-093", "journal_seq": 7})
    logger.warning("second", extra={"component": "ARG-093"})
    handler.close()
    lines = _lines(sender)
    assert [line["message"] for _, line in lines] == ["first", "second"]
    assert {frozenset(labels) for labels, _ in lines} == {frozenset({"service", "level"})}
    assert {labels["level"] for labels, _ in lines} == {"INFO", "WARNING"}
    # The line is the one of the standard output: journal_seq travels in it, not as a label.
    assert lines[0][1]["journal_seq"] == 7
    assert lines[0][1]["service"] == "argos-test"


def test_a_full_queue_drops_and_counts_without_blocking() -> None:
    gate = threading.Event()  # the sender is stuck until the test opens the gate
    sender = _Sender(gate=gate)
    handler = LokiHandler(
        "argos-test", sender=sender, batch_size=1, flush_seconds=0.01, max_queue=3
    )
    logger = _logger(handler)
    for n in range(50):
        logger.info("line %s", n, extra={"component": "ARG-093"})
    assert handler.dropped > 0
    gate.set()
    handler.close()


def test_an_unreachable_loki_drops_and_never_raises() -> None:
    handler = LokiHandler("argos-test", sender=_Sender(fail=True), batch_size=2, flush_seconds=60)
    logger = _logger(handler)
    for n in range(4):
        logger.info("line %s", n, extra={"component": "ARG-093"})
    handler.close()
    assert handler.dropped == 4


def test_without_a_loki_url_only_the_standard_output_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARGOS_LOKI_URL", raising=False)
    configure_logging("argos-test", stream=io.StringIO())
    assert not any(isinstance(h, LokiHandler) for h in logging.getLogger().handlers)


def test_with_a_loki_url_the_handler_is_added_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_LOKI_URL", "http://127.0.0.1:9/loki/api/v1/push")
    configure_logging("argos-test", stream=io.StringIO())
    configure_logging("argos-test", stream=io.StringIO())
    lokis = [h for h in logging.getLogger().handlers if isinstance(h, LokiHandler)]
    assert len(lokis) == 1
    get_logger(__name__, "ARG-093").info("to an address nobody listens on")
    monkeypatch.delenv("ARGOS_LOKI_URL")
    configure_logging("argos-test", stream=io.StringIO())  # and removed again
    assert not any(isinstance(h, LokiHandler) for h in logging.getLogger().handlers)
