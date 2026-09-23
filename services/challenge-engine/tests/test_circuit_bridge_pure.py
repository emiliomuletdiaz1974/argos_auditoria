"""ARG-013 → ARG-043 · what the connector shouts on the bus reaches the campaign as a signal.

A connector opens its circuit breaker when a source is suffering and says so on the bus. Until now
nobody listened: the campaign kept asking and the console showed no pause. This bridge turns that
event into the `circuit_open` signal of every running campaign, with a reason a person can read.
"""

import asyncio
from typing import Any

from argos_challenges.bridge import DURABLE, SUBJECT, on_circuit_open
from argos_connector.events import CIRCUIT_OPEN_SUBJECT


def test_the_bridge_listens_to_the_subject_the_connector_publishes() -> None:
    assert SUBJECT == CIRCUIT_OPEN_SUBJECT
    assert DURABLE


def test_every_running_campaign_is_signalled_with_the_system_and_a_readable_reason() -> None:
    sent: list[tuple[str, list[Any]]] = []

    async def signal(campaign_id: str, arguments: list[Any]) -> None:
        sent.append((campaign_id, arguments))

    handle = on_circuit_open(lambda: ["c-1", "c-2"], signal)
    asyncio.run(handle({"system_id": "s-7", "p50_ms": 4200}, {}))

    assert [campaign for campaign, _ in sent] == ["c-1", "c-2"]
    system_id, reason = sent[0][1]
    assert system_id == "s-7"
    assert "4200" in reason and "p50" in reason


def test_without_a_running_campaign_nothing_is_signalled() -> None:
    sent: list[str] = []

    async def signal(campaign_id: str, arguments: list[Any]) -> None:
        sent.append(campaign_id)

    asyncio.run(on_circuit_open(list, signal)({"system_id": "s-7", "p50_ms": 1}, {}))
    assert sent == []
