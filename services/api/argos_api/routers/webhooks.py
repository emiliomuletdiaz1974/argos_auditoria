"""Webhooks: what the GRC of the client subscribes to, and what was delivered (ARG-079)."""

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from argos_api.authz import require_perm
from argos_api.http import IdempotencyKey, Page, Paging, pending

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class NewWebhook(BaseModel):
    url: str = Field(min_length=8, description="https endpoint of the client")
    events: list[str] = Field(min_length=1, description="events it subscribes to")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe an endpoint",
    dependencies=[Depends(require_perm("webhooks.create"))],
)
def subscribe(body: NewWebhook, idempotency_key: IdempotencyKey = None) -> dict[str, Any]:
    pending("the webhook subscription")


@router.get(
    "", summary="List the subscriptions", dependencies=[Depends(require_perm("webhooks.read"))]
)
def list_webhooks(paging: Paging) -> Page:
    pending("the webhook listing")


@router.get(
    "/{webhook_id}/deliveries",
    summary="Deliveries and their retries",
    dependencies=[Depends(require_perm("webhooks.read"))],
)
def deliveries(webhook_id: str, paging: Paging) -> Page:
    pending("the delivery listing")
