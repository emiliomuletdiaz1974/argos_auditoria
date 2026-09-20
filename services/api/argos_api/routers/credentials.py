"""Credentials: issue, consult and revoke the verifiable credential of a campaign (ARG-077)."""

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from argos_api.authz import require_perm
from argos_api.http import IdempotencyKey, pending

router = APIRouter(prefix="/credentials", tags=["credentials"])


class NewCredential(BaseModel):
    campaign_id: str = Field(min_length=1)


class Revocation(BaseModel):
    reason: str = Field(min_length=1)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Issue the credential of a campaign",
    dependencies=[Depends(require_perm("credentials.create"))],
)
def issue(body: NewCredential, idempotency_key: IdempotencyKey = None) -> dict[str, Any]:
    pending("issuing a credential")


@router.get(
    "/{credential_id}",
    summary="A credential and its status",
    dependencies=[Depends(require_perm("credentials.read"))],
)
def credential(credential_id: str) -> dict[str, Any]:
    pending("the credential detail")


@router.post(
    "/{credential_id}/revoke",
    summary="Revoke a credential",
    dependencies=[Depends(require_perm("credentials.revoke"))],
)
def revoke(credential_id: str, body: Revocation) -> dict[str, Any]:
    pending("revoking a credential")
