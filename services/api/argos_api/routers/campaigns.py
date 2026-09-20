"""Campaigns: plan, launch, watch and approve the gates (ARG-075)."""

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from argos_api.authz import require_perm
from argos_api.http import IdempotencyKey, Page, Paging, pending

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class NewCampaign(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    scope: dict[str, Any] = Field(default_factory=dict)


class GateApproval(BaseModel):
    note: str = ""


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Plan a campaign",
    dependencies=[Depends(require_perm("campaigns.create"))],
)
def plan(body: NewCampaign, idempotency_key: IdempotencyKey = None) -> dict[str, Any]:
    pending("planning a campaign")


@router.get(
    "", summary="List the campaigns", dependencies=[Depends(require_perm("campaigns.read"))]
)
def list_campaigns(paging: Paging) -> Page:
    pending("the campaign listing")


@router.get(
    "/{campaign_id}",
    summary="State of a campaign",
    dependencies=[Depends(require_perm("campaigns.read"))],
)
def campaign(campaign_id: str) -> dict[str, Any]:
    pending("the campaign detail")


@router.post(
    "/{campaign_id}/launch",
    summary="Launch the planned campaign",
    dependencies=[Depends(require_perm("campaigns.launch"))],
)
def launch(campaign_id: str) -> dict[str, Any]:
    pending("launching a campaign")


@router.get(
    "/{campaign_id}/plan",
    summary="Plan resolved over the snapshot, before probing",
    dependencies=[Depends(require_perm("campaigns.read"))],
)
def plan_preview(campaign_id: str) -> dict[str, Any]:
    pending("the previous plan")


@router.get(
    "/{campaign_id}/progress",
    summary="Progress of the run",
    dependencies=[Depends(require_perm("campaigns.read"))],
)
def progress(campaign_id: str) -> dict[str, Any]:
    pending("campaign progress")


@router.get(
    "/{campaign_id}/gates",
    summary="Human control points and their approvals",
    dependencies=[Depends(require_perm("campaigns.read"))],
)
def gates(campaign_id: str) -> dict[str, Any]:
    pending("the campaign gates")


@router.post(
    "/{campaign_id}/gates/{gate}/approve",
    summary="Approve a control point",
    dependencies=[Depends(require_perm("campaigns.approve"))],
)
def approve(campaign_id: str, gate: str, body: GateApproval) -> dict[str, Any]:
    pending("approving a gate")
