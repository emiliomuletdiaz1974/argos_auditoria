"""Temporal worker for the campaign domain (foundation of ARG-043…049).

Usage: uv run python -m argos_challenges.worker
"""

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from argos_common.config import ArgosConfig, get_config
from argos_common.dynamic_db import start_from_config
from argos_common.logs import configure_logging, get_logger
from argos_common.secret_stores import VaultSecretStore
from argos_events import Bus, bus_from_config

from .activities import ChallengeActivities, record_in_journal, smoke_probe
from .bridge import DURABLE, SIGNAL, SUBJECT, on_circuit_open
from .store import running_campaigns
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
            campaign.check_gate,
            campaign.set_campaign_status,
            campaign.probe,
            campaign.wait_window,
            campaign.evaluate_unit,
            campaign.seal,
            campaign.check_reversions,
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


def campaign_activities(
    cfg: ArgosConfig | None = None, bus: Bus | None = None
) -> ChallengeActivities:
    """The campaign activities bound to the configured database, Vault, OPA and bus.

    With a bus, sealing a campaign is announced on `argos.campaign.sealed`; whoever needs to act
    on it (the evidence service) listens. The campaign never waits for them.
    """
    config = cfg or get_config()
    token = config.VAULT_TOKEN.get_secret_value() if config.VAULT_TOKEN else ""
    secrets = VaultSecretStore(config.VAULT_ADDR, token)
    opa_token = config.OPA_TOKEN.get_secret_value() if config.OPA_TOKEN else None
    return ChallengeActivities(
        config.DATABASE_URL, secrets, config.OPA_URL, bus, opa_token=opa_token
    )


async def listen_for_open_circuits(client: Client, bus: Bus, dsn: str) -> None:
    """A source that is suffering pauses in the campaigns that are asking it (ARG-013 → ARG-043)."""

    async def signal(campaign_id: str, arguments: list[Any]) -> None:
        handle = client.get_workflow_handle(f"campaign-{campaign_id}")
        await handle.signal(SIGNAL, args=arguments)

    await bus.subscribe(SUBJECT, DURABLE, on_circuit_open(lambda: running_campaigns(dsn), signal))


async def main() -> None:
    cfg = get_config()
    configure_logging("argos-campaign-worker", cfg.LOG_LEVEL)
    start_from_config(cfg)  # F09-05: the dynamic credential, before any connection
    client = await Client.connect(cfg.TEMPORAL_ADDRESS, namespace="default")
    bus = bus_from_config("argos-campaign-worker", cfg)
    await bus.connect()
    await listen_for_open_circuits(client, bus, cfg.DATABASE_URL)
    worker = await create_worker(client, campaign=campaign_activities(cfg, bus))
    get_logger(__name__, "ARG-007").info(f"worker ready on queue {TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
