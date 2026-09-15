"""Circuit-open notification so the campaign can reschedule (ARG-013 → ARG-043)."""

import asyncio

from argos_events import Bus

from .budget import CircuitListener

CIRCUIT_OPEN_SUBJECT = "argos.campaign.circuit_open"
CIRCUIT_OPEN_EVENT = "campaign.circuit_open.v1"


def bus_circuit_listener(bus: Bus, loop: asyncio.AbstractEventLoop) -> CircuitListener:
    """Bridge the synchronous budget to the asyncio bus; the publication is audited."""

    def notify(system_id: str, p50_ms: float) -> None:
        asyncio.run_coroutine_threadsafe(
            bus.publish(
                CIRCUIT_OPEN_SUBJECT,
                CIRCUIT_OPEN_EVENT,
                {"system_id": system_id, "p50_ms": round(p50_ms)},
                audit=True,
            ),
            loop,
        )

    return notify
