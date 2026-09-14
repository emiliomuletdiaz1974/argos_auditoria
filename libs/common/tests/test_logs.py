"""Structured logging with mandatory fields (ARG-001)."""

import io
import json
from typing import Any

import pytest

from argos_common.logs import configure_logging, get_logger


def _lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_mandatory_fields() -> None:
    stream = io.StringIO()
    configure_logging("svc-test", "INFO", stream)
    get_logger("test", "ARG-005").info("hello ñ")
    [entry] = _lines(stream)
    assert {"timestamp", "level", "service", "component", "logger", "message"} <= entry.keys()
    assert entry["service"] == "svc-test"
    assert entry["component"] == "ARG-005"
    assert entry["message"] == "hello ñ"
    assert entry["timestamp"].endswith("+00:00")


def test_per_call_optional_fields_keep_the_component() -> None:
    stream = io.StringIO()
    configure_logging("svc", "INFO", stream)
    get_logger("test", "ARG-012").info("entry", extra={"journal_seq": 42, "trace_id": "t-1"})
    [entry] = _lines(stream)
    assert entry["journal_seq"] == 42
    assert entry["trace_id"] == "t-1"
    assert entry["component"] == "ARG-012"
    assert "campaign_id" not in entry


def test_honours_the_level() -> None:
    stream = io.StringIO()
    configure_logging("svc", "WARNING", stream)
    log = get_logger("test", "ARG-001")
    log.info("no")
    log.warning("yes")
    assert [e["message"] for e in _lines(stream)] == ["yes"]


def test_reconfiguring_does_not_duplicate_output() -> None:
    stream = io.StringIO()
    configure_logging("svc", "INFO", io.StringIO())
    configure_logging("svc", "INFO", stream)
    get_logger("test", "ARG-001").info("once")
    assert len(_lines(stream)) == 1


def test_serializes_exceptions() -> None:
    stream = io.StringIO()
    configure_logging("svc", "INFO", stream)
    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        get_logger("test", "ARG-001").exception("failure")
    assert "ZeroDivisionError" in _lines(stream)[0]["exception"]


def test_invalid_component_format() -> None:
    with pytest.raises(ValueError, match="ARG-NNN"):
        get_logger("test", "ARGOS")
