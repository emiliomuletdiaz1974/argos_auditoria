"""Campaign API: plan, launch, watch, approve and confirm (ARG-047, ADR-0008).

The RACI of the contract is plain: ARGOS runs and evidences, the client approves. This API is where
that happens. A campaign manager plans and launches; a DPO reviewer approves the gates, authorises
the injection of a synthetic subject and moves a finding; the client confirms what it did in its own
systems. Every one of those actions is a person, and every one of them enters the chained journal.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Path, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from argos_auth import Identity, JwtValidator
from argos_challenges import findings as findings_module
from argos_challenges import synthetic as synthetic_module
from argos_challenges.api.auth import MANAGER_ROLE, REVIEWER_ROLE, role_dependency
from argos_challenges.seal import verify_seal
from argos_challenges.store import (
    CampaignStateError,
    approvals_needed,
    campaign_record,
    create_campaign,
    grant_approval,
)
from argos_common.errors import ArgosError

SERVICE_NAME = "argos-campaigns"
DEV_HOST = "127.0.0.1"
DEV_PORT = 8003
CAMPAIGN_WORKFLOW = "CampaignWorkflow"

# Identifiers are uuid columns: anything else is refused here, not by PostgreSQL with a 500.
Uuid = Annotated[
    str,
    Path(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
]
GateName = Annotated[str, Path(pattern=r"^[a-z_]{1,32}$")]
_log = logging.getLogger(__name__)
MAX_TEXT = 2_000
MAX_SCOPE_BYTES = 16_384
TemporalStarter = Callable[[str], Awaitable[str]]
RemediationStarter = Callable[[dict[str, Any]], Awaitable[str]]
TemporalSignaller = Callable[[str, str, str], Awaitable[None]]


class NewCampaign(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    scope: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scope")
    @classmethod
    def _bounded(cls, scope: dict[str, Any]) -> dict[str, Any]:
        # The scope lands in JSONB and in the journal: a request cannot be megabytes of it.
        if len(json.dumps(scope, ensure_ascii=False).encode("utf-8")) > MAX_SCOPE_BYTES:
            raise ValueError(f"the scope is larger than {MAX_SCOPE_BYTES} bytes")
        return scope


class Transition(BaseModel):
    to: str = Field(max_length=32)
    note: str = Field(default="", max_length=MAX_TEXT)
    risk_expiry: date | None = None


class Injection(BaseModel):
    subject_id: str = Field(max_length=64)
    system_id: str = Field(max_length=64)
    point: str = Field(min_length=1, max_length=MAX_TEXT)
    method: str = Field(min_length=1, max_length=MAX_TEXT)
    revert_procedure: str = Field(min_length=1, max_length=MAX_TEXT)


class Confirmation(BaseModel):
    right: str = Field(default="erasure", max_length=32)


class RemediationScope(BaseModel):
    campaign_id: str | None = Field(default=None, max_length=64)


def create_app(
    dsn: str,
    validator: JwtValidator,
    start_campaign: TemporalStarter | None = None,
    signal_campaign: TemporalSignaller | None = None,
    start_remediation: RemediationStarter | None = None,
    publish_docs: bool = False,
) -> FastAPI:
    """The campaign API. The two callables talk to Temporal; tests pass their own.

    The route map and its models are published only when asked for (development): outside it
    they would describe roles and payloads to anyone on the network, token or not.
    """
    app = FastAPI(
        title="ARGOS campaigns",
        version="1",
        docs_url="/docs" if publish_docs else None,
        redoc_url="/redoc" if publish_docs else None,
        openapi_url="/openapi.json" if publish_docs else None,
    )

    @app.exception_handler(psycopg.Error)
    async def _store_unavailable(request: Request, error: psycopg.Error) -> JSONResponse:
        # The driver's message names the host, the SQL or the constraint: it stays in the log,
        # as its type only, and the client learns that the store did not answer.
        _log.warning("campaign store error", extra={"error": type(error).__name__})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "the campaign store is not available"},
        )

    # FastAPI reads the dependency from the annotation, so no call sits in a default value.
    reader = Annotated[Identity, Depends(role_dependency(validator))]  # noqa: N806
    manager = Annotated[Identity, Depends(role_dependency(validator, MANAGER_ROLE))]  # noqa: N806
    reviewer = Annotated[Identity, Depends(role_dependency(validator, REVIEWER_ROLE))]  # noqa: N806

    def _fail(error: ArgosError) -> HTTPException:
        return HTTPException(status.HTTP_409_CONFLICT, str(error))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME}

    @app.post("/campaigns", status_code=status.HTTP_201_CREATED)
    def plan(body: NewCampaign, identity: manager) -> dict[str, str]:
        campaign_id = create_campaign(dsn, body.name, body.scope, identity.actor)
        return {"campaign_id": campaign_id}

    @app.post("/campaigns/{campaign_id}/launch")
    async def launch(campaign_id: Uuid, identity: manager) -> dict[str, str]:
        if start_campaign is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no campaign runner attached")
        try:
            campaign_record(dsn, campaign_id)
        except CampaignStateError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
        workflow_id = await start_campaign(campaign_id)
        return {"campaign_id": campaign_id, "workflow_id": workflow_id}

    @app.get("/campaigns/{campaign_id}")
    def read(campaign_id: Uuid, identity: reader) -> dict[str, Any]:
        try:
            record = campaign_record(dsn, campaign_id)
        except CampaignStateError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
        record["seal_verified"] = verify_seal(dsn, campaign_id) if record.get("seal") else False
        return record

    @app.get("/campaigns/{campaign_id}/verdicts")
    def verdicts(campaign_id: Uuid, identity: reader) -> list[dict[str, Any]]:
        with psycopg.connect(dsn) as conn:
            rows = conn.execute(
                "SELECT challenge_id, node_key, result, verdict_hash FROM argos.verdicts "
                "WHERE campaign_id = %s ORDER BY challenge_id, node_key",
                (campaign_id,),
            ).fetchall()
        fields = ("challenge_id", "node_key", "result", "verdict_hash")
        return [dict(zip(fields, row, strict=True)) for row in rows]

    @app.get("/campaigns/{campaign_id}/findings")
    def campaign_findings(campaign_id: Uuid, identity: reader) -> list[dict[str, Any]]:
        with psycopg.connect(dsn) as conn:
            rows = conn.execute(
                "SELECT id::text, challenge_id, node_key, severity, status, occurrences "
                "FROM argos.findings WHERE campaign_id = %s ORDER BY severity DESC, id",
                (campaign_id,),
            ).fetchall()
        fields = ("id", "challenge_id", "node_key", "severity", "status", "occurrences")
        return [dict(zip(fields, row, strict=True)) for row in rows]

    @app.get("/campaigns/{campaign_id}/gates")
    def gates(campaign_id: Uuid, identity: reader) -> list[dict[str, Any]]:
        with psycopg.connect(dsn) as conn:
            rows = conn.execute(
                "SELECT r.gate, r.payload, count(a.approved_by) "
                "FROM argos.approval_requests r "
                "LEFT JOIN argos.approvals a ON a.campaign_id = r.campaign_id AND a.gate = r.gate "
                "WHERE r.campaign_id = %s GROUP BY r.gate, r.payload ORDER BY r.gate",
                (campaign_id,),
            ).fetchall()
        return [
            {
                "gate": row[0],
                "payload": row[1],
                "approvals": int(row[2]),
                "needed": approvals_needed(str(row[0])),
            }
            for row in rows
        ]

    @app.post("/campaigns/{campaign_id}/gates/{gate}/approve")
    async def approve(campaign_id: Uuid, gate: GateName, identity: reviewer) -> dict[str, Any]:
        needed = approvals_needed(gate)
        try:
            granted, enough = grant_approval(dsn, campaign_id, gate, identity.actor, needed)
        except CampaignStateError as error:
            raise _fail(error) from None
        if enough and signal_campaign is not None:
            await signal_campaign(campaign_id, "approve", gate)
        return {
            "gate": gate,
            "approvals": granted,
            "needed": needed,
            "state": "approved" if enough else "awaiting_second_approval",
        }

    @app.post("/campaigns/{campaign_id}/synthetic/authorize", status_code=status.HTTP_201_CREATED)
    def authorize(campaign_id: Uuid, body: Injection, identity: reviewer) -> dict[str, str]:
        try:
            injection_id = synthetic_module.authorize_injection(
                dsn,
                body.subject_id,
                body.system_id,
                body.point,
                body.method,
                body.revert_procedure,
                identity.actor,
                campaign_id=campaign_id,
            )
        except synthetic_module.SyntheticError as error:
            raise _fail(error) from None
        return {"injection_id": injection_id, "campaign_id": campaign_id}

    @app.post("/synthetic/{injection_id}/confirm-injection")
    def confirm_injection(injection_id: Uuid, identity: manager) -> dict[str, str]:
        try:
            synthetic_module.confirm_injection(dsn, injection_id, identity.actor)
        except synthetic_module.SyntheticError as error:
            raise _fail(error) from None
        return {"injection_id": injection_id, "state": "injected"}

    @app.post("/synthetic/{injection_id}/confirm-exercise")
    def confirm_exercise(
        injection_id: Uuid, body: Confirmation, identity: manager
    ) -> dict[str, str]:
        try:
            synthetic_module.confirm_exercise(dsn, injection_id, body.right, identity.actor)
        except synthetic_module.SyntheticError as error:
            raise _fail(error) from None
        return {"injection_id": injection_id, "state": "exercised"}

    @app.post("/synthetic/{injection_id}/confirm-revert")
    def confirm_revert(injection_id: Uuid, identity: manager) -> dict[str, str]:
        try:
            synthetic_module.confirm_revert(dsn, injection_id, identity.actor)
        except synthetic_module.SyntheticError as error:
            raise _fail(error) from None
        return {"injection_id": injection_id, "state": "reverted"}

    @app.post("/remediation")
    async def remediation(body: RemediationScope, identity: manager) -> dict[str, str]:
        if start_remediation is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "no remediation runner attached"
            )
        scope: dict[str, Any] = {"requested_by": identity.actor}
        if body.campaign_id:
            scope["campaign_id"] = body.campaign_id
        workflow_id = await start_remediation(scope)
        return {"workflow_id": workflow_id}

    @app.post("/findings/{finding_id}/transition")
    def move_finding(finding_id: Uuid, body: Transition, identity: reviewer) -> dict[str, str]:
        try:
            previous = findings_module.transition(
                dsn, finding_id, body.to, identity.actor, body.note, body.risk_expiry
            )
        except findings_module.FindingError as error:
            raise _fail(error) from None
        return {"finding_id": finding_id, "from": previous, "to": body.to}

    return app
