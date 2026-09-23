"""The process that actually delivers the webhooks (ARG-079).

Two halves meet here. The bus half listens to the events a subscription may ask for and writes one
delivery per subscription; the Temporal half runs `WebhookDelivery`, which retries with its own
backoff so a slow ITSM never holds up the campaign that produced the event. The API only writes
subscriptions: nothing is delivered from the request that caused it.

Usage: uv run python -m argos_api.webhooks.worker
"""

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from argos_api.webhooks.dispatch import WebhookActivities
from argos_api.webhooks.subscriber import DURABLE, SUBJECTS, on_event
from argos_api.webhooks.workflow import TASK_QUEUE, WebhookDelivery
from argos_common.config import ArgosConfig, get_config
from argos_common.logs import configure_logging, get_logger
from argos_common.secret_stores import VaultSecretStore
from argos_events import Bus, bus_from_config

SERVICE = "argos-webhook-worker"


def activities(cfg: ArgosConfig) -> WebhookActivities:
    token = cfg.VAULT_TOKEN.get_secret_value() if cfg.VAULT_TOKEN else ""
    return WebhookActivities(
        cfg.DATABASE_URL,
        VaultSecretStore(cfg.VAULT_ADDR, token),
        allowed=allowed_targets(cfg),
    )


def allowed_targets(cfg: ArgosConfig) -> tuple[str, ...]:
    """The private destinations the installer allowed for webhooks (SEC-031)."""
    return tuple(t.strip() for t in cfg.WEBHOOK_ALLOWED_TARGETS.split(",") if t.strip())


async def create_worker(client: Client, cfg: ArgosConfig) -> Worker:
    return Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[WebhookDelivery],
        activities=[activities(cfg).deliver],
    )


async def listen(client: Client, bus: Bus, dsn: str) -> None:
    """Each event becomes one delivery per subscription, and one workflow per delivery."""

    async def start(delivery_id: str) -> None:
        await client.start_workflow(
            WebhookDelivery.run,
            delivery_id,
            id=f"webhook-{delivery_id}",
            task_queue=TASK_QUEUE,
        )

    for subject, event_type in SUBJECTS.items():
        # One durable per subject: JetStream binds a consumer to one subscription, and sharing the
        # name across the three would leave two of them unheard.
        await bus.subscribe(subject, f"{DURABLE}-{event_type}", on_event(subject, dsn, start))


async def main() -> None:  # pragma: no cover - process entry point
    cfg = get_config()
    configure_logging(SERVICE, cfg.LOG_LEVEL)
    client = await Client.connect(cfg.TEMPORAL_ADDRESS, namespace="default")
    bus = bus_from_config(SERVICE, cfg)
    await bus.connect()
    await listen(client, bus, cfg.DATABASE_URL)
    worker = await create_worker(client, cfg)
    get_logger(__name__, "ARG-079").info(f"webhook worker ready on queue {TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
