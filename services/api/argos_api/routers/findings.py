"""Findings: their life cycle and the verification of a remediation (ARG-076)."""

from datetime import date
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from argos_api.http import Page, Paging, pending

router = APIRouter(prefix="/findings", tags=["findings"])


class Transition(BaseModel):
    to: str = Field(description="target state of the finding")
    note: str = ""
    risk_expiry: date | None = Field(default=None, description="only when accepting the risk")


@router.get("", summary="List the findings")
def list_findings(paging: Paging) -> Page:
    pending("the finding listing")


@router.get("/{finding_id}", summary="A finding with its evidence")
def finding(finding_id: str) -> dict[str, Any]:
    pending("the finding detail")


@router.post("/{finding_id}/transition", summary="Move the finding to another state")
def transition(finding_id: str, body: Transition) -> dict[str, Any]:
    pending("the finding transition")


@router.post("/{finding_id}/verify", summary="Re-run the challenge to verify the remediation")
def verify(finding_id: str) -> dict[str, Any]:
    pending("the remediation check")
