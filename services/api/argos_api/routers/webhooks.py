"""Webhooks: what the GRC of the client subscribes to, and what was delivered (ARG-079).

The secret arrives once, in the subscription, and goes straight to the secret store: no response,
listing or journal entry carries it. The inbox of each subscription answers «did it arrive?».
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import IdempotencyKey, caller, database
from argos_api.paging import Page, Paging, paginate
from argos_api.webhooks.destination import (
    DestinationRefusedError,
    check_destination,
    resolve_host,
)
from argos_api.webhooks.store import (
    EVENT_TYPES,
    SecretWriter,
    create_webhook,
    list_deliveries,
    list_webhooks,
    webhook_exists,
)
from argos_api.webhooks.templates import load_templates

router = APIRouter(prefix="/webhooks", tags=["webhooks"], route_class=CoreRoute)


class NewWebhook(BaseModel):
    url: str = Field(
        pattern="^https://", max_length=2000, description="endpoint of the client, https only"
    )
    events: list[str] = Field(min_length=1, description="events it subscribes to")
    template: str = Field(default="generic", description="servicenow, jira, generic…")
    secret: str = Field(
        min_length=16, max_length=512, description="shared secret to sign; never returned"
    )

    @field_validator("events")
    @classmethod
    def _known_events(cls, events: list[str]) -> list[str]:
        unknown = sorted(set(events) - set(EVENT_TYPES))
        if unknown:
            raise ValueError(f"unknown events {unknown}: one of {list(EVENT_TYPES)}")
        return sorted(set(events))

    @field_validator("template")
    @classmethod
    def _known_template(cls, template: str) -> str:
        if template not in load_templates():
            raise ValueError(f"unknown template {template!r}: one of {sorted(load_templates())}")
        return template


def _secrets(request: Request) -> SecretWriter:
    store: SecretWriter | None = getattr(request.app.state, "webhook_secrets", None)
    if store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no secret store attached")
    return store


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe an endpoint",
    dependencies=[Depends(require_perm("webhooks.create"))],
)
def subscribe(
    request: Request, body: NewWebhook, idempotency_key: IdempotencyKey = None
) -> dict[str, Any]:
    allowed = getattr(request.app.state, "webhook_allowed", ())
    resolve = getattr(request.app.state, "webhook_resolve", resolve_host)
    try:
        check_destination(body.url, resolve=resolve, allowed=allowed)
    except DestinationRefusedError as refused:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(refused)) from None
    return create_webhook(
        database(request),
        _secrets(request),
        url=body.url,
        events=body.events,
        template=body.template,
        secret=body.secret,
        created_by=caller(request).actor,
    )


@router.get(
    "", summary="List the subscriptions", dependencies=[Depends(require_perm("webhooks.read"))]
)
def list_all(request: Request, paging: Paging) -> Page:
    rows = list_webhooks(database(request), paging.limit + 1, paging.position)
    return paginate(rows, paging.limit)


@router.get(
    "/{webhook_id}/deliveries",
    summary="Deliveries and their retries",
    dependencies=[Depends(require_perm("webhooks.read"))],
)
def deliveries(request: Request, webhook_id: UUID, paging: Paging) -> Page:
    dsn = database(request)
    if not webhook_exists(dsn, str(webhook_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no webhook {webhook_id}")
    rows = list_deliveries(dsn, str(webhook_id), paging.limit + 1, paging.position)
    return paginate(rows, paging.limit)
