"""Temporal worker and hourly schedule of the inventory rescan (ARG-030).

Usage: uv run python -m argos_inventory.scheduler.worker
"""

import asyncio

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.worker import Worker

from argos_common.config import ArgosConfig, get_config
from argos_common.logs import configure_logging, get_logger
from argos_common.secret_stores import VaultSecretStore
from argos_events import bus_from_config
from argos_inventory.scheduler.activities import InventoryActivities
from argos_inventory.scheduler.workflows import RescanPlanner, ScanSystem

TASK_QUEUE = "argos-inventory"
SCHEDULE_ID = "inventory-rescan-hourly"
PLANNER_WORKFLOW_ID = "inventory-rescan-planner"
HOURLY = "0 * * * *"


def create_worker(
    client: Client, activities: InventoryActivities, task_queue: str = TASK_QUEUE
) -> Worker:
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[RescanPlanner, ScanSystem],
        activities=[
            activities.score_systems,
            activities.run_scan,
            activities.compute_run_deltas,
            activities.analyze_system,
            activities.refresh_inventory,
        ],
    )


async def ensure_schedule(
    client: Client,
    task_queue: str = TASK_QUEUE,
    schedule_id: str = SCHEDULE_ID,
    paused: bool = False,
) -> bool:
    """Create the hourly planner schedule; False when it already exists (it is left untouched)."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            RescanPlanner.run, id=PLANNER_WORKFLOW_ID, task_queue=task_queue
        ),
        spec=ScheduleSpec(cron_expressions=[HOURLY]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        state=ScheduleState(paused=paused),
    )
    try:
        await client.create_schedule(schedule_id, schedule)
    except ScheduleAlreadyRunningError:
        return False
    return True


async def run(cfg: ArgosConfig) -> None:
    if cfg.VAULT_TOKEN is None:
        raise ValueError("ARGOS_VAULT_TOKEN is required by the inventory scheduler")
    bus = bus_from_config("inventory-scheduler", cfg)
    await bus.connect()
    try:
        client = await Client.connect(cfg.TEMPORAL_ADDRESS, namespace="default")
        secrets = VaultSecretStore(cfg.VAULT_ADDR, cfg.VAULT_TOKEN.get_secret_value())
        activities = InventoryActivities(cfg.DATABASE_URL, secrets, bus)
        created = await ensure_schedule(client)
        log = get_logger(__name__, "ARG-030")
        log.info(f"schedule {SCHEDULE_ID} {'created' if created else 'already present'}")
        log.info(f"inventory worker ready on queue {TASK_QUEUE}")
        await create_worker(client, activities).run()
    finally:
        await bus.close()


def main() -> None:  # pragma: no cover - process entry point
    cfg = get_config()
    configure_logging("argos-inventory-scheduler", cfg.LOG_LEVEL)
    asyncio.run(run(cfg))


if __name__ == "__main__":  # pragma: no cover
    main()
