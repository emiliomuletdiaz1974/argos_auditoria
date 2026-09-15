"""ARG-006 · event bus against the make dev NATS server."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import nats
import pytest

from argos_common.journal_pg import PostgresJournal
from argos_events import Bus, ensure_streams

pytestmark = pytest.mark.integration
NATS_URL = os.environ.get("ARGOS_TEST_NATS", "nats://127.0.0.1:4222")


@pytest.fixture
async def bus() -> AsyncIterator[Bus]:
    b = Bus("svc-test", NATS_URL, retry_delay=0.1)
    await b.connect()
    yield b
    await b.close()


def _names() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return f"argos.discovery.test_{suffix}", f"test_{suffix}"


async def test_ensure_streams_is_idempotent() -> None:
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    await ensure_streams(js)
    await ensure_streams(js)
    info = await js.stream_info("CHALLENGE")
    assert "argos.campaign.>" in (info.config.subjects or [])
    await nc.close()


async def test_publish_and_consume(bus: Bus) -> None:
    subject, durable = _names()
    received: asyncio.Future[tuple[dict[str, Any], dict[str, Any]]] = (
        asyncio.get_running_loop().create_future()
    )

    async def handler(data: dict[str, Any], event: dict[str, Any]) -> None:
        received.set_result((data, event))

    await bus.subscribe(subject, durable, handler)
    await bus.publish(subject, "discovery.table_found.v1", {"table": "appointments"})
    data, event = await asyncio.wait_for(received, 5)
    assert data == {"table": "appointments"}
    assert event["type"] == "eu.argos.discovery.table_found.v1"
    await bus.js.delete_consumer("DISCOVERY", durable)


async def test_failing_handler_is_redelivered(bus: Bus) -> None:
    subject, durable = _names()
    attempts = 0
    done: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def handler(data: dict[str, Any], event: dict[str, Any]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("transient failure")
        done.set_result(attempts)

    await bus.subscribe(subject, durable, handler)
    await bus.publish(subject, "discovery.table_found.v1", {"table": "x"})
    assert await asyncio.wait_for(done, 10) == 3
    await bus.js.delete_consumer("DISCOVERY", durable)


async def test_malformed_message_is_discarded_without_retries(bus: Bus) -> None:
    subject, durable = _names()
    calls: list[dict[str, Any]] = []
    valid: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    async def handler(data: dict[str, Any], event: dict[str, Any]) -> None:
        calls.append(data)
        valid.set_result(None)

    await bus.subscribe(subject, durable, handler)
    await bus.js.publish(subject, b"this is not json")
    await bus.publish(subject, "discovery.table_found.v1", {"table": "good"})
    await asyncio.wait_for(valid, 5)
    await asyncio.sleep(0.5)
    info = await bus.js.consumer_info("DISCOVERY", durable)
    assert calls == [{"table": "good"}]
    assert info.num_ack_pending == 0
    await bus.js.delete_consumer("DISCOVERY", durable)


async def test_audited_publish_writes_a_journal_entry(migrated_db: str) -> None:
    journal = PostgresJournal(migrated_db)
    b = Bus("svc-test", NATS_URL, journal=journal)
    await b.connect()
    subject, _ = _names()
    before = journal.head()[0]
    await b.publish(subject, "discovery.table_found.v1", {"table": "t"}, audit=True)
    await b.close()
    assert journal.head()[0] == before + 1
    last = list(journal.read(from_seq=before + 1))[0]
    assert last.action == "event.publish" and last.actor == "system:svc-test"


async def test_subject_outside_the_streams(bus: Bus) -> None:
    with pytest.raises(ValueError):
        await bus.publish("other.thing", "discovery.table_found.v1", {})
