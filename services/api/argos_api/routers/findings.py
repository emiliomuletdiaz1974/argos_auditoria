"""Findings: their life cycle and the verification of a remediation (ARG-076)."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import Page, Paging, pending

router = APIRouter(prefix="/findings", tags=["findings"], route_class=CoreRoute)
RISK_ACCEPTED = "risk_accepted"


class Transition(BaseModel):
    to: str = Field(description="target state of the finding")
    note: str = ""
    risk_expiry: date | None = Field(default=None, description="only when accepting the risk")

    @model_validator(mode="after")
    def _accepting_a_risk_needs_a_reason(self) -> "Transition":
        if self.to == RISK_ACCEPTED and not self.note.strip():
            raise ValueError("accepting a risk needs a note saying why")
        return self


@router.get("", summary="List the findings", dependencies=[Depends(require_perm("findings.read"))])
def list_findings(paging: Paging) -> Page:
    pending("the finding listing")


@router.get(
    "/{finding_id}",
    summary="A finding with its evidence",
    dependencies=[Depends(require_perm("findings.read"))],
)
def finding(finding_id: str) -> dict[str, Any]:
    pending("the finding detail")


@router.post(
    "/{finding_id}/transition",
    summary="Move the finding to another state",
    dependencies=[Depends(require_perm("findings.transition"))],
)
def transition(finding_id: str, body: Transition) -> dict[str, Any]:
    pending("the finding transition")


@router.post(
    "/{finding_id}/verify",
    summary="Re-run the challenge to verify the remediation",
    dependencies=[Depends(require_perm("findings.verify"))],
)
def verify(finding_id: str) -> dict[str, Any]:
    pending("the remediation check")
