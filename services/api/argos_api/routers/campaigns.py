"""Campaigns: plan, launch, watch and approve the gates (ARG-075)."""

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from argos_api.http import IdempotencyKey, Page, Paging, pending

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class NewCampaign(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    scope: dict[str, Any] = Field(default_factory=dict)


class GateApproval(BaseModel):
    note: str = ""


@router.post("", status_code=status.HTTP_201_CREATED, summary="Plan a campaign")
def plan(body: NewCampaign, idempotency_key: IdempotencyKey = None) -> dict[str, Any]:
    pending("planning a campaign")


@router.get("", summary="List the campaigns")
def list_campaigns(paging: Paging) -> Page:
    pending("the campaign listing")


@router.get("/{campaign_id}", summary="State of a campaign")
def campaign(campaign_id: str) -> dict[str, Any]:
    pending("the campaign detail")


@router.post("/{campaign_id}/launch", summary="Launch the planned campaign")
def launch(campaign_id: str) -> dict[str, Any]:
    pending("launching a campaign")


@router.get("/{campaign_id}/plan", summary="Plan resolved over the snapshot, before probing")
def plan_preview(campaign_id: str) -> dict[str, Any]:
    pending("the previous plan")


@router.get("/{campaign_id}/progress", summary="Progress of the run")
def progress(campaign_id: str) -> dict[str, Any]:
    pending("campaign progress")


@router.get("/{campaign_id}/gates", summary="Human control points and their approvals")
def gates(campaign_id: str) -> dict[str, Any]:
    pending("the campaign gates")


@router.post("/{campaign_id}/gates/{gate}/approve", summary="Approve a control point")
def approve(campaign_id: str, gate: str, body: GateApproval) -> dict[str, Any]:
    pending("approving a gate")
