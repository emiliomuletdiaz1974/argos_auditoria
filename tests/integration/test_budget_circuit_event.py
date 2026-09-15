"""ARG-013 · an open circuit publishes an audited event on the make dev NATS server."""

import asyncio
import os
import uuid
from typing import Any

import pytest

from argos_common.ids import uuid7
from argos_common.journal_pg import PostgresJournal
from argos_connector.budget import LoadBudget
from argos_connector.events import CIRCUIT_OPEN_SUBJECT, bus_circuit_listener
from argos_events import Bus

pytestmark = pytest.mark.integration
NATS_URL = os.environ.get("ARGOS_TEST_NATS", "nats://127.0.0.1:4222")


async def test_open_circuit_publishes_an_audited_event(migrated_db: str) -> None:
    journal = PostgresJournal(migrated_db)
    bus = Bus("svc-connector-test", NATS_URL, journal=journal)
    await bus.connect()
    system_id = str(uuid7())
    durable = f"test_circuit_{uuid.uuid4().hex[:8]}"
    received: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

    async def handler(data: dict[str, Any], event: dict[str, Any]) -> None:
        if data.get("system_id") == system_id and not received.done():
            received.set_result(event)

    await bus.subscribe(CIRCUIT_OPEN_SUBJECT, durable, handler)
    budget = LoadBudget(
        system_id,
        {"latency_p50_limit_ms": 10},
        on_circuit_open=bus_circuit_listener(bus, asyncio.get_running_loop()),
    )
    head_before = journal.head()[0]

    def slow_probes() -> None:
        for _ in range(5):
            budget.observe_latency(50)

    await asyncio.to_thread(slow_probes)
    event = await asyncio.wait_for(received, 10)
    assert event["type"] == "eu.argos.campaign.circuit_open.v1"
    assert event["data"] == {"system_id": system_id, "p50_ms": 50}
    assert budget.state == "open"
    assert "event.publish" in [e.action for e in journal.read(from_seq=head_before + 1)]
    await bus.js.delete_consumer("CHALLENGE", durable)
    await bus.close()
