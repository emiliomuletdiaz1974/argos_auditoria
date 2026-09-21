"""Findings: the whole why, the transitions a person may take, and closure by re-run (ARG-076).

A finding closed by hand is an opinion; one closed because its challenge passed again is evidence.
So no route of this router reaches `closed_compliant` or `reopened`: they belong to the re-run of
ARG-049, which `verify` starts, and the domain refuses them from any person as well. The console
does not keep its own copy of the state machine: each finding says where a person may move it.
"""

import asyncio
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import caller, database
from argos_api.paging import Page, Paging, paginate
from argos_api.runner import CampaignRunner
from argos_challenges.findings import (
    SEVERITIES,
    STATUSES,
    VERIFICATION_ONLY,
    FindingError,
    finding_detail,
    list_findings,
    transition,
)
from argos_ontology.editorial.compiler import read_obligation

router = APIRouter(prefix="/findings", tags=["findings"], route_class=CoreRoute)
RISK_ACCEPTED = "risk_accepted"
AWAITING_VERIFICATION = "pending_verification"
ORDER = "order_key"


class Transition(BaseModel):
    to: str = Field(description="target state of the finding")
    note: str = ""
    risk_expiry: date | None = Field(default=None, description="only when accepting the risk")

    @model_validator(mode="after")
    def _accepting_a_risk_is_documented(self) -> "Transition":
        if self.to not in STATUSES:
            raise ValueError(f"unknown status: {self.to}")
        if self.to == RISK_ACCEPTED and not self.note.strip():
            raise ValueError("accepting a risk needs a note saying why")
        if self.to == RISK_ACCEPTED and self.risk_expiry is None:
            raise ValueError("accepting a risk needs an expiry date")
        return self


def _found(dsn: str, finding_id: UUID) -> dict[str, Any]:
    found = finding_detail(dsn, str(finding_id))
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no finding {finding_id}")
    return found


def _one_of(value: str | None, allowed: tuple[str, ...], name: str) -> str | None:
    if value is not None and value not in allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown {name}: {value}")
    return value


@router.get(
    "",
    summary="List the findings, worst first",
    dependencies=[Depends(require_perm("findings.read"))],
)
def list_all(
    request: Request,
    paging: Paging,
    status_is: Annotated[
        str | None, Query(alias="status", description="one of the finding states")
    ] = None,
    severity: Annotated[str | None, Query(description="low, medium, high or critical")] = None,
    campaign_id: Annotated[UUID | None, Query(description="only this campaign")] = None,
) -> Page:
    rows = list_findings(
        database(request),
        paging.limit + 1,
        paging.position,
        status=_one_of(status_is, STATUSES, "status"),
        severity=_one_of(severity, SEVERITIES, "severity"),
        campaign_id=str(campaign_id) if campaign_id else None,
    )
    return paginate(rows, paging.limit, at=ORDER)


@router.get(
    "/{finding_id}",
    summary="A finding with its whole why",
    dependencies=[Depends(require_perm("findings.read"))],
)
def finding(request: Request, finding_id: UUID) -> dict[str, Any]:
    found = _found(database(request), finding_id)
    spec = read_obligation(str(found["obligation"]))
    found["obligation"] = {
        "id": found["obligation"],
        "norm": spec.norm if spec else None,
        "article": spec.article if spec else None,
        "title": spec.title if spec else None,
        "summary": spec.summary if spec else None,
    }
    return found


@router.post(
    "/{finding_id}/transition",
    summary="Move the finding to another state",
    dependencies=[Depends(require_perm("findings.transition"))],
)
def move(request: Request, finding_id: UUID, body: Transition) -> dict[str, Any]:
    if body.to in VERIFICATION_ONLY:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"a finding reaches {body.to} only through a re-run of its challenge: use verify",
        )
    dsn = database(request)
    _found(dsn, finding_id)
    try:
        previous = transition(
            dsn, str(finding_id), body.to, caller(request).actor, body.note, body.risk_expiry
        )
    except FindingError as refused:
        raise HTTPException(status.HTTP_409_CONFLICT, str(refused)) from None
    return {"finding_id": str(finding_id), "from": previous, "to": body.to}


@router.post(
    "/{finding_id}/verify",
    summary="Re-run the challenge to verify the remediation",
    dependencies=[Depends(require_perm("findings.verify"))],
)
async def verify(request: Request, finding_id: UUID) -> dict[str, Any]:
    runner: CampaignRunner | None = getattr(request.app.state, "campaign_runner", None)
    if runner is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no campaign runner attached")
    found = await asyncio.to_thread(_found, database(request), finding_id)
    if found["status"] != AWAITING_VERIFICATION:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"only a finding awaiting verification is re-run; this one is {found['status']}",
        )
    scope = {"finding_id": str(finding_id), "requested_by": caller(request).actor}
    workflow_id = await runner.remediate(scope)
    return {"finding_id": str(finding_id), "workflow_id": workflow_id}
