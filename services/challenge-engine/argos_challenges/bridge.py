"""From the bus to the running campaign: a circuit that opens becomes a pause with a reason.

A connector opens its circuit breaker when a source is suffering (ARG-013) and publishes it. The
campaign workflow already knows how to pause a system —`circuit_open(system_id, reason)`—, but
nobody was translating one into the other, so the pause never reached the console. This does, for
every campaign that is running: the event carries the system and its measured p50, and the reason
is written so that whoever reads the progress understands why that system stopped.
"""

import asyncio
from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import Any

from argos_connector.events import CIRCUIT_OPEN_SUBJECT

SUBJECT = CIRCUIT_OPEN_SUBJECT
DURABLE = "campaign-circuit"
SIGNAL = "circuit_open"
REASON = "el conector abrió el cortacircuitos: p50 de {p50_ms} ms sobre el presupuesto"

Running = Callable[[], Sequence[str]]
Signaller = Callable[[str, list[Any]], Coroutine[Any, Any, None]]
Handler = Callable[[Mapping[str, Any], Mapping[str, Any]], Coroutine[Any, Any, None]]


def on_circuit_open(running: Running, signal: Signaller) -> Handler:
    """Handler for the bus: signal every running campaign that this system is paused."""

    async def handle(data: Mapping[str, Any], _event: Mapping[str, Any]) -> None:
        system_id = str(data["system_id"])
        reason = REASON.format(p50_ms=data.get("p50_ms", "?"))
        for campaign_id in await asyncio.to_thread(running):
            await signal(campaign_id, [system_id, reason])

    return handle
