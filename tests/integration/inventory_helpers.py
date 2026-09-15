"""Shared helpers of the inventory integration tests: scan, ingest and probe runner (F03-06)."""

import asyncio
from collections.abc import Callable
from functools import partial
from typing import Any

from argos_common.secret_stores import VaultSecretStore
from argos_connector.probes import ProbeResult, ProbeSpec
from argos_inventory.discovery.probes import run_probe
from argos_inventory.discovery.scanner import scan_system
from argos_inventory.graph.store import GraphStore
from argos_inventory.ingest.handlers import Ingestor

from .sources import VAULT, connector_token, register_catalog_system


class RecordingBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(
        self, subject: str, event_type: str, data: dict[str, Any], audit: bool = False
    ) -> int:
        self.events.append((subject, event_type, data))
        return len(self.events)


def secret_store() -> VaultSecretStore:
    return VaultSecretStore(VAULT, connector_token())


def probe_runner(dsn: str) -> Callable[[str, ProbeSpec], ProbeResult]:
    return partial(run_probe, dsn, secret_store())


def scan_and_ingest(dsn: str, name: str) -> str:
    """Register a catalog system in `dsn`, scan it and ingest every event it produced."""
    system_id = register_catalog_system(dsn, name)
    scan_bus = RecordingBus()
    ingestor = Ingestor(GraphStore(dsn), dsn, RecordingBus())

    async def go() -> None:
        await scan_system(dsn, secret_store(), scan_bus, system_id)
        for _, event_type, data in scan_bus.events:
            await ingestor.handle(data, {"type": f"eu.argos.{event_type}"})

    asyncio.run(go())
    return system_id
