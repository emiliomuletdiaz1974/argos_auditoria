"""Credentials: preview, issue, consult and revoke the credential of a campaign (ARG-077).

Issuing is an explicit act of the DPO. The preview shows exactly what the credential will assert,
and the issuance names the dossier it saw by its hash: if the dossier changed in between (a late
time stamp makes a new one), nothing is issued and the preview has to be read again. So what is
signed is always what was shown.
"""

import asyncio
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import IdempotencyKey, caller, database
from argos_api.routers.evidence import evidence_of
from argos_evidence.credential.issue import CredentialError, revoke_credential
from argos_evidence.reads import credential_preview, credential_state, current_dossier

router = APIRouter(prefix="/credentials", tags=["credentials"], route_class=CoreRoute)


class NewCredential(BaseModel):
    campaign_id: UUID
    dossier_sha256: str = Field(
        pattern="^[0-9a-f]{64}$", description="the dossier the preview showed"
    )


class Revocation(BaseModel):
    reason: str = Field(min_length=1)


def _current(dsn: str, campaign_id: UUID) -> dict[str, Any]:
    dossier = current_dossier(dsn, str(campaign_id))
    if dossier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} has no dossier yet")
    return dossier


@router.get(
    "/preview",
    summary="Exactly what the credential of a campaign would assert, before issuing it",
    dependencies=[Depends(require_perm("credentials.create"))],
)
def preview(
    request: Request, campaign_id: Annotated[UUID, Query(description="the sealed campaign")]
) -> dict[str, Any]:
    evidence = evidence_of(request)
    return credential_preview(evidence.store, _current(database(request), campaign_id))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Issue the credential of a campaign",
    dependencies=[Depends(require_perm("credentials.create"))],
)
async def issue(
    request: Request, body: NewCredential, idempotency_key: IdempotencyKey = None
) -> dict[str, Any]:
    evidence = evidence_of(request)
    dsn = database(request)
    dossier = await asyncio.to_thread(_current, dsn, body.campaign_id)
    if dossier["sha256"] != body.dossier_sha256:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "the dossier changed since the preview: read the preview again before issuing",
        )
    credential_id = await asyncio.to_thread(
        evidence.issue_credential_now, str(body.campaign_id), body.dossier_sha256
    )
    state = await asyncio.to_thread(credential_state, dsn, evidence.store, credential_id)
    if state is None:  # pragma: no cover - issue_credential_now has just stored it
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "the credential vanished")
    return state


@router.get(
    "/{credential_id}",
    summary="A credential and its status",
    dependencies=[Depends(require_perm("credentials.read"))],
)
def credential(request: Request, credential_id: str) -> dict[str, Any]:
    evidence = evidence_of(request)
    state = credential_state(database(request), evidence.store, credential_id)
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no credential {credential_id}")
    return state


@router.post(
    "/{credential_id}/revoke",
    summary="Revoke a credential",
    dependencies=[Depends(require_perm("credentials.revoke"))],
)
def revoke(request: Request, credential_id: str, body: Revocation) -> dict[str, Any]:
    try:
        revoke_credential(database(request), credential_id, body.reason, caller(request).actor)
    except CredentialError as refused:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(refused)) from None
    return {"credential_id": credential_id, "revoked": True, "reason": body.reason}
