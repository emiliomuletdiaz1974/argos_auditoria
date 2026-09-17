"""Temporal worker for the campaign domain (foundation of ARG-043…049).

Usage: uv run python -m argos_challenges.worker
"""

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from argos_common.config import ArgosConfig, get_config
from argos_common.logs import configure_logging, get_logger
from argos_common.secret_stores import VaultSecretStore

from .activities import ChallengeActivities, record_in_journal, smoke_probe
from .workflows import CampaignWorkflow, RemediationRun, SmokeCampaign, SystemRun

TASK_QUEUE = "argos-campaigns"


async def create_worker(
    client: Client,
    task_queue: str = TASK_QUEUE,
    campaign: ChallengeActivities | None = None,
) -> Worker:
    activities: list[Callable[..., Any]] = [smoke_probe, record_in_journal]
    if campaign is not None:
        activities += [
            campaign.prepare_campaign,
            campaign.request_approval,
            campaign.set_campaign_status,
            campaign.probe,
            campaign.wait_window,
            campaign.evaluate_unit,
            campaign.seal,
            campaign.start_remediation,
            campaign.transition_finding,
        ]
    registered: Sequence[Callable[..., Any]] = activities
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[SmokeCampaign, CampaignWorkflow, SystemRun, RemediationRun],
        activities=registered,
    )


def campaign_activities(cfg: ArgosConfig | None = None) -> ChallengeActivities:
    """The campaign activities bound to the configured database, Vault and OPA."""
    config = cfg or get_config()
    token = config.VAULT_TOKEN.get_secret_value() if config.VAULT_TOKEN else ""
    secrets = VaultSecretStore(config.VAULT_ADDR, token)
    return ChallengeActivities(config.DATABASE_URL, secrets, config.OPA_URL)


async def main() -> None:
    cfg = get_config()
    configure_logging("argos-campaign-worker", cfg.LOG_LEVEL)
    client = await Client.connect(cfg.TEMPORAL_ADDRESS, namespace="default")
    worker = await create_worker(client, campaign=campaign_activities(cfg))
    get_logger(__name__, "ARG-007").info(f"worker ready on queue {TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
