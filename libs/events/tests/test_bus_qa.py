"""QA-25 · what the bus does when things go wrong.

- QA-001: an event whose handler failed on every delivery is kept (dead letter) and its last
  failure says so; it is not silently dropped by JetStream.
- QA-004: the bus takes a renewed certificate when it loses its connection, before reconnecting.
- QA-005: a publish carries its id as `Nats-Msg-Id` (JetStream drops a retried duplicate), a
  caller that retries can fix that id, and nothing is journaled for an event that cannot even be
  serialised.
"""

import asyncio
import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest

from argos_events import Bus


class _Msg:
    def __init__(self, deliveries: int) -> None:
        self.subject = "argos.discovery.table_found"
        self.data = b'{"id": "e-1", "type": "eu.argos.discovery.table_found.v1", "data": {"t": 1}}'
        self.metadata = SimpleNamespace(num_delivered=deliveries)
        self.acted: list[str] = []

    async def ack(self) -> None:
        self.acted.append("ack")

    async def nak(self, delay: float | None = None) -> None:
        self.acted.append("nak")

    async def term(self) -> None:
        self.acted.append("term")


class _JetStream:
    def __init__(self) -> None:
        self.callback: Any = None
        self.published: list[tuple[str, bytes, dict[str, str] | None]] = []

    async def subscribe(self, subject: str, durable: str, cb: Any, **kwargs: Any) -> None:
        self.callback = cb

    async def publish(
        self, subject: str, payload: bytes, headers: dict[str, str] | None = None
    ) -> Any:
        self.published.append((subject, payload, headers))
        return SimpleNamespace(seq=len(self.published))


def _bus(**kwargs: Any) -> tuple[Bus, _JetStream]:
    bus = Bus("inventory-ingest", "nats://nats:4222", retry_delay=0, max_deliveries=5, **kwargs)
    js = _JetStream()
    bus._js = js  # type: ignore[assignment]
    return bus, js


async def _failing(data: dict[str, Any], event: dict[str, Any]) -> None:
    raise RuntimeError("database unavailable")


def test_the_last_failed_delivery_keeps_the_event_as_a_dead_letter() -> None:
    kept: list[dict[str, Any]] = []
    bus, js = _bus(dead_letter=kept.append)
    asyncio.run(bus.subscribe("argos.discovery.>", "inventory-ingest", _failing))
    early, last = _Msg(deliveries=2), _Msg(deliveries=5)
    asyncio.run(js.callback(early))
    assert early.acted == ["nak"] and kept == [], "an early failure is simply redelivered"
    asyncio.run(js.callback(last))
    assert last.acted == ["term"], "handed over to the dead letters, not left to vanish"
    [letter] = kept
    assert letter["durable"] == "inventory-ingest" and letter["deliveries"] == 5
    assert letter["event"]["id"] == "e-1" and "database unavailable" in letter["error"]


def test_a_dead_letter_that_cannot_be_kept_leaves_the_event_to_be_redelivered() -> None:
    def broken(letter: dict[str, Any]) -> None:
        raise OSError("dead letter store down")

    bus, js = _bus(dead_letter=broken)
    asyncio.run(bus.subscribe("argos.discovery.>", "inventory-ingest", _failing))
    last = _Msg(deliveries=5)
    asyncio.run(js.callback(last))
    assert last.acted == ["nak"], "never terminated without being kept somewhere"


def test_a_publish_carries_its_id_for_deduplication_and_a_retry_can_fix_it() -> None:
    bus, js = _bus()
    asyncio.run(bus.publish("argos.evidence.x", "evidence.sealed.v1", {"a": 1}, event_id="fixed-1"))
    asyncio.run(bus.publish("argos.evidence.x", "evidence.sealed.v1", {"a": 1}, event_id="fixed-1"))
    assert [h and h.get("Nats-Msg-Id") for _, _, h in js.published] == ["fixed-1", "fixed-1"]


def test_nothing_is_journaled_for_an_event_that_cannot_be_serialised() -> None:
    entries: list[Any] = []
    journal = SimpleNamespace(append=lambda *entry: entries.append(entry))
    bus, _ = _bus(journal=journal)
    with pytest.raises(TypeError):
        asyncio.run(
            bus.publish(
                "argos.evidence.x", "evidence.sealed.v1", {"at": dt.datetime.now()}, audit=True
            )
        )
    assert entries == []


def test_the_bus_takes_a_renewed_certificate_when_it_loses_its_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refreshed: list[int] = []
    context = object()
    tls = SimpleNamespace(client_context=lambda: context, refresh=lambda: refreshed.append(1))
    captured: dict[str, Any] = {}

    class Connection:
        def jetstream(self) -> Any:
            return object()

    async def connect(url: str, **kwargs: Any) -> Connection:
        captured.update(kwargs)
        return Connection()

    monkeypatch.setattr("argos_events.nats.connect", connect)
    bus = Bus("svc", "nats://nats:4222", tls=tls)  # type: ignore[arg-type]
    asyncio.run(bus.connect())
    assert captured["tls"] is context
    asyncio.run(captured["disconnected_cb"]())
    assert refreshed == [1]
