"""Temporal worker of the evidence service, started by each sealed campaign (ARG-061…068).

Usage: uv run python -m argos_evidence.worker

The campaign engine does not call this service: it announces the seal on NATS
(`argos.campaign.sealed`) and goes on. This worker listens and starts one
evidence workflow per campaign, under an id derived from it, so a repeated
announcement starts nothing twice.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import psycopg
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

from argos_common.config import get_config
from argos_common.logs import configure_logging, get_logger
from argos_events import Bus
from argos_evidence.service import build_activities
from argos_evidence.settings import EvidenceSettings
from argos_evidence.workflow import TASK_QUEUE, EvidenceWorkflow

SEALED_SUBJECT = "argos.campaign.sealed"
DURABLE = "evidence-on-seal"
_log = get_logger(__name__, "ARG-061")


def workflow_id(campaign_id: str) -> str:
    return f"evidence-{campaign_id}"


def holds_sealed(dsn: str, campaign_id: str) -> bool:
    """Whether this deployment's database holds that campaign, sealed."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT 1 FROM argos.campaigns WHERE id::text = %s AND status = 'sealed'",
            (campaign_id,),
        ).fetchone()
    return row is not None


def on_seal(
    client: Client, settings: EvidenceSettings, dsn: str, task_queue: str = TASK_QUEUE
) -> Callable[[Mapping[str, Any], Mapping[str, Any]], Awaitable[None]]:
    async def handle(data: Mapping[str, Any], _event: Mapping[str, Any]) -> None:
        campaign_id = str(data["campaign_id"])
        # The stream is shared: an announcement of a campaign this deployment does not hold (another
        # database, a campaign that no longer exists) is acknowledged and left alone.
        if not await asyncio.to_thread(holds_sealed, dsn, campaign_id):
            _log.info(f"sealed campaign {campaign_id} is not held here: no evidence started")
            return
        try:
            await client.start_workflow(
                EvidenceWorkflow.run,
                args=[campaign_id, settings.STAMP_ATTEMPTS, settings.STAMP_WAIT_SECONDS],
                id=workflow_id(campaign_id),
                task_queue=task_queue,
            )
        except WorkflowAlreadyStartedError:
            return

    return handle


async def main() -> None:  # pragma: no cover - process entry point
    config = get_config()
    settings = EvidenceSettings()
    configure_logging("argos-evidence-worker", config.LOG_LEVEL)
    activities = build_activities(config, settings)
    client = await Client.connect(config.TEMPORAL_ADDRESS, namespace="default")
    worker = Worker(
        client, task_queue=TASK_QUEUE, workflows=[EvidenceWorkflow], activities=activities.all()
    )
    bus = Bus("argos-evidence-worker", config.NATS_URL)
    await bus.connect()
    await bus.subscribe(SEALED_SUBJECT, DURABLE, on_seal(client, settings, config.DATABASE_URL))
    _log.info(f"evidence worker ready on queue {TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
