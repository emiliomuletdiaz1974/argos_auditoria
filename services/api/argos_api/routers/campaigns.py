"""Campaigns: plan, look before running, launch, watch and approve the gates (ARG-075).

The campaign belongs to the engine (`argos_challenges.store`) and Temporal runs it: here there is
no INSERT of our own (deviation note ARG-071-080). A campaign manager plans and launches; a DPO
reviewer reads the literal plan and approves the gates, two different people for sampling.
"""

import asyncio
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, Field, field_validator

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import IdempotencyKey, caller, database
from argos_api.paging import Page, Paging, paginate
from argos_api.runner import CampaignRunner
from argos_challenges.seal import verify_seal
from argos_challenges.store import (
    CampaignStateError,
    approvals_needed,
    campaign_gates,
    campaign_plan,
    campaign_record,
    create_campaign,
    grant_approval,
    list_campaigns,
    list_verdicts,
)
from argos_challenges.synthetic import SyntheticError, authorize_injection

router = APIRouter(prefix="/campaigns", tags=["campaigns"], route_class=CoreRoute)

# Free text and the scope land in JSONB and in the journal: a request cannot be megabytes of them.
MAX_TEXT = 2_000
MAX_SCOPE_BYTES = 16_384
GateName = Annotated[str, Path(pattern=r"^[a-z_]{1,32}$")]


class NewCampaign(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    scope: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scope")
    @classmethod
    def _bounded(cls, scope: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(scope, ensure_ascii=False).encode("utf-8")) > MAX_SCOPE_BYTES:
            raise ValueError(f"the scope is larger than {MAX_SCOPE_BYTES} bytes")
        return scope


class GateApproval(BaseModel):
    note: str = Field(default="", max_length=MAX_TEXT)


def _runner(request: Request) -> CampaignRunner:
    runner: CampaignRunner | None = getattr(request.app.state, "campaign_runner", None)
    if runner is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no campaign runner attached")
    return runner


def _record(dsn: str, campaign_id: str) -> dict[str, Any]:
    try:
        return campaign_record(dsn, campaign_id)
    except CampaignStateError as unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(unknown)) from None


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Plan a campaign",
    dependencies=[Depends(require_perm("campaigns.create"))],
)
def plan(
    request: Request, body: NewCampaign, idempotency_key: IdempotencyKey = None
) -> dict[str, Any]:
    # The key is handled around the route (CoreRoute): a retry never reaches this line twice.
    campaign_id = create_campaign(database(request), body.name, body.scope, caller(request).actor)
    return {"campaign_id": campaign_id}


@router.get(
    "", summary="List the campaigns", dependencies=[Depends(require_perm("campaigns.read"))]
)
def list_all(request: Request, paging: Paging) -> Page:
    rows = list_campaigns(database(request), paging.limit + 1, paging.position)
    return paginate(rows, paging.limit)


@router.get(
    "/{campaign_id}",
    summary="State of a campaign",
    dependencies=[Depends(require_perm("campaigns.read"))],
)
def campaign(request: Request, campaign_id: UUID) -> dict[str, Any]:
    dsn = database(request)
    record = _record(dsn, str(campaign_id))
    record["seal_verified"] = verify_seal(dsn, str(campaign_id)) if record.get("seal") else False
    return record


@router.post(
    "/{campaign_id}/launch",
    summary="Launch the planned campaign",
    dependencies=[Depends(require_perm("campaigns.launch"))],
)
async def launch(request: Request, campaign_id: UUID) -> dict[str, Any]:
    runner = _runner(request)
    await asyncio.to_thread(_record, database(request), str(campaign_id))
    workflow_id = await runner.start(str(campaign_id))
    return {"campaign_id": str(campaign_id), "workflow_id": workflow_id}


@router.get(
    "/{campaign_id}/plan",
    summary="What the campaign will ask, literally, before it asks anything",
    dependencies=[Depends(require_perm("campaigns.read"))],
)
def plan_preview(request: Request, campaign_id: UUID) -> dict[str, Any]:
    try:
        preview = campaign_plan(database(request), str(campaign_id))
    except CampaignStateError as unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(unknown)) from None
    if preview is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "no plan until the campaign is prepared: launch it and it stops at the start gate",
        )
    return preview


@router.get(
    "/{campaign_id}/progress",
    summary="Progress of the run, as the workflow tells it",
    dependencies=[Depends(require_perm("campaigns.read"))],
)
async def progress(request: Request, campaign_id: UUID) -> dict[str, Any]:
    runner = _runner(request)
    await asyncio.to_thread(_record, database(request), str(campaign_id))
    try:
        return await runner.progress(str(campaign_id))
    except LookupError:
        raise HTTPException(status.HTTP_409_CONFLICT, "the campaign is not running") from None


@router.get(
    "/{campaign_id}/gates",
    summary="Human control points and their approvals",
    dependencies=[Depends(require_perm("campaigns.read"))],
)
def gates(request: Request, campaign_id: UUID) -> dict[str, Any]:
    dsn = database(request)
    _record(dsn, str(campaign_id))
    return {"items": campaign_gates(dsn, str(campaign_id))}


@router.post(
    "/{campaign_id}/gates/{gate}/approve",
    summary="Approve a control point",
    dependencies=[Depends(require_perm("campaigns.approve"))],
)
async def approve(
    request: Request, campaign_id: UUID, gate: GateName, body: GateApproval
) -> dict[str, Any]:
    needed = approvals_needed(gate)
    try:
        granted, enough = await asyncio.to_thread(
            grant_approval, database(request), str(campaign_id), gate, caller(request).actor, needed
        )
    except CampaignStateError as refused:
        raise HTTPException(status.HTTP_409_CONFLICT, str(refused)) from None
    runner: CampaignRunner | None = getattr(request.app.state, "campaign_runner", None)
    if enough and runner is not None:
        await runner.signal(str(campaign_id), "approve", gate)
    return {
        "gate": gate,
        "approvals": granted,
        "needed": needed,
        "state": "approved" if enough else "awaiting_second_approval",
    }


class Injection(BaseModel):
    """One injection point of the synthetic subject, as the DPO authorises it (ADR-0008)."""

    subject_id: UUID = Field(description="a subject already generated and recorded")
    system_id: UUID
    point: str = Field(min_length=1, max_length=MAX_TEXT)
    method: str = Field(min_length=1, max_length=MAX_TEXT)
    revert_procedure: str = Field(
        min_length=1, max_length=MAX_TEXT, description="how the client undoes it"
    )

    @field_validator("revert_procedure")
    @classmethod
    def _undoing_it_is_written_down(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an injection is authorised only with its revert procedure")
        return value


@router.get(
    "/{campaign_id}/verdicts",
    summary="Verdicts of the campaign, as they were written",
    dependencies=[Depends(require_perm("campaigns.read"))],
)
def verdicts(request: Request, campaign_id: UUID, paging: Paging) -> Page:
    dsn = database(request)
    _record(dsn, str(campaign_id))
    rows = list_verdicts(dsn, str(campaign_id), paging.limit + 1, paging.position)
    return paginate(rows, paging.limit)


@router.post(
    "/{campaign_id}/synthetic/authorize",
    status_code=status.HTTP_201_CREATED,
    summary="Authorise one injection point of the synthetic subject",
    dependencies=[Depends(require_perm("synthetic.authorize"))],
)
def authorize(request: Request, campaign_id: UUID, body: Injection) -> dict[str, str]:
    dsn = database(request)
    _record(dsn, str(campaign_id))
    try:
        injection_id = authorize_injection(
            dsn,
            str(body.subject_id),
            str(body.system_id),
            body.point,
            body.method,
            body.revert_procedure,
            caller(request).actor,
            campaign_id=str(campaign_id),
        )
    except SyntheticError as refused:
        raise HTTPException(status.HTTP_409_CONFLICT, str(refused)) from None
    return {"injection_id": injection_id, "campaign_id": str(campaign_id)}


@router.post(
    "/{campaign_id}/remediation",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run what a campaign found, to verify the remediation",
    dependencies=[Depends(require_perm("campaigns.remediate"))],
)
async def remediation(request: Request, campaign_id: UUID) -> dict[str, str]:
    runner = _runner(request)
    await asyncio.to_thread(_record, database(request), str(campaign_id))
    scope = {"campaign_id": str(campaign_id), "requested_by": caller(request).actor}
    return {"workflow_id": await runner.remediate(scope)}
