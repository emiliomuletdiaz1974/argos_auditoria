"""Inventory ingest service: one durable consumer of the DISCOVERY stream (ARG-022).

Usage: uv run python -m argos_inventory.ingest.main
"""

import asyncio

from argos_common.config import ArgosConfig, get_config
from argos_common.logs import configure_logging, get_logger
from argos_events import bus_from_config
from argos_inventory.graph.store import GraphStore

from .handlers import Ingestor

DURABLE = "inventory-ingest"


async def run(cfg: ArgosConfig) -> None:
    bus = bus_from_config("inventory-ingest", cfg)
    await bus.connect()
    ingestor = Ingestor(GraphStore(cfg.DATABASE_URL), cfg.DATABASE_URL, bus)
    await bus.subscribe("argos.discovery.>", durable=DURABLE, handler=ingestor.handle)
    get_logger(__name__, "ARG-022").info("inventory ingest subscribed to argos.discovery.>")
    await asyncio.Event().wait()


def main() -> None:
    cfg = get_config()
    configure_logging("argos-inventory-ingest", cfg.LOG_LEVEL)
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
