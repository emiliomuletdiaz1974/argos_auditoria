"""Campaigns: plan, look before running, launch, watch and approve the gates (ARG-075).

The campaign belongs to the engine (`argos_challenges.store`) and Temporal runs it: here there is
no INSERT of our own (deviation note ARG-071-080). A campaign manager plans and launches; a DPO
reviewer reads the literal plan and approves the gates, two different people for sampling.
"""

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

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
)

router = APIRouter(prefix="/campaigns", tags=["campaigns"], route_class=CoreRoute)


class NewCampaign(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    scope: dict[str, Any] = Field(default_factory=dict)


class GateApproval(BaseModel):
    note: str = ""


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
    request: Request, campaign_id: UUID, gate: str, body: GateApproval
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
