"""From the bus to the inbox: which events become deliveries (ARG-079).

A finding opened becomes an incident, a campaign sealed a notification, a gate awaiting approval a
notice to whoever approves. Each subscription to the event gets its delivery, and each delivery its
own workflow, so one slow ITSM does not hold up the others.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from argos_api.webhooks.store import enqueue_event

SUBJECTS = {
    "argos.challenge.finding_opened": "finding_opened",
    "argos.campaign.sealed": "campaign_sealed",
    "argos.campaign.approval_requested": "approval_requested",
}
DURABLE = "webhooks"

Starter = Callable[[str], Awaitable[None]]
Handler = Callable[[Mapping[str, Any], Mapping[str, Any]], Awaitable[None]]


def on_event(subject: str, dsn: str, start: Starter) -> Handler:
    event_type = SUBJECTS[subject]

    async def handle(data: Mapping[str, Any], _event: Mapping[str, Any]) -> None:
        for delivery_id in await asyncio.to_thread(enqueue_event, dsn, event_type, dict(data)):
            await start(delivery_id)

    return handle
