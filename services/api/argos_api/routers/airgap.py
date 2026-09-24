"""ARG-090 · the airlock through the API (F09-13).

`POST /airgap/imports` scans the medium and imports what verifies; `POST /airgap/exports` writes
one kind of the closed list to it. Only `platform_admin`, with the second factor: what comes in can
change the appliance, and what goes out leaves it. Every file and every export is recorded by the
gate itself, in the journal and in the security log.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from argos_airgap import Gate
from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import caller

router = APIRouter(prefix="/airgap", tags=["airgap"], route_class=CoreRoute)


class ExportRequest(BaseModel):
    # A free text on purpose: a kind outside the closed list must reach the gate to be refused and
    # recorded, not stop at the validation of the body.
    kind: str = Field(
        min_length=1, max_length=40, description="tsq, diagnostics, dossier or credential"
    )
    campaign_id: str | None = Field(default=None, max_length=64)
    diagnostics_id: str | None = Field(default=None, max_length=64)
    approved_index_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def _gate(request: Request) -> Gate:
    gate: Gate | None = getattr(request.app.state, "airgap", None)
    if gate is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the airlock is not configured")
    return gate


@router.post(
    "/imports",
    summary="Scan the medium and import what verifies; say what was refused and why",
    dependencies=[Depends(require_perm("airgap.import"))],
)
def scan(request: Request) -> dict[str, Any]:
    results = _gate(request).scan(caller(request).actor)
    return {
        "results": [
            {
                "file": r.file,
                "kind": r.kind,
                "result": r.result,
                "reason": r.reason,
                "sha256": r.sha256,
                "size": r.size,
            }
            for r in results
        ]
    }


@router.post(
    "/exports",
    status_code=status.HTTP_201_CREATED,
    summary="Write one kind of the closed list of exports to the medium",
    dependencies=[Depends(require_perm("airgap.export"))],
)
def export(request: Request, body: ExportRequest) -> dict[str, Any]:
    params = body.model_dump(exclude={"kind"}, exclude_none=True)
    try:
        done = _gate(request).export(body.kind, caller(request).actor, params)
    except PermissionError as refused:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(refused)) from None
    except (LookupError, ValueError) as missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(missing)) from None
    return {"id": done.id, "kind": done.kind, "files": done.files}
