"""Temporal worker for the campaign domain (foundation of ARG-043…049).

Usage: uv run python -m argos_challenges.worker
"""

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from argos_common.config import get_config
from argos_common.logs import configure_logging, get_logger

from .activities import record_in_journal, smoke_probe
from .workflows import SmokeCampaign

TASK_QUEUE = "argos-campaigns"


async def create_worker(client: Client, task_queue: str = TASK_QUEUE) -> Worker:
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[SmokeCampaign],
        activities=[smoke_probe, record_in_journal],
    )


async def main() -> None:
    cfg = get_config()
    configure_logging("argos-campaign-worker", cfg.LOG_LEVEL)
    client = await Client.connect(cfg.TEMPORAL_ADDRESS, namespace="default")
    worker = await create_worker(client)
    get_logger(__name__, "ARG-007").info(f"worker ready on queue {TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
