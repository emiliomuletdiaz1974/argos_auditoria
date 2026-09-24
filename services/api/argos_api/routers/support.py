"""ARG-088 · the diagnostic package through the API (F09-11).

The API does not collect: the collector runs next to the orchestrator (on the host in development,
on the node in the appliance) and leaves the preview in the folder they share. The API queues the
request, shows the preview in clear (index and every file) and, when the operator approves that
index, encrypts exactly those bytes for support. A file that changed after the index, or an index
other than the one approved, gives no package.

Only `platform_admin`; the package, which is what leaves, also asks for the second factor.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import caller
from argos_api.security_events import security_event
from argos_support import DiagnosticsError, DiagnosticsStore, build_package

router = APIRouter(prefix="/support", tags=["support"], route_class=CoreRoute)


@dataclass(frozen=True, slots=True)
class SupportDiagnostics:
    """The folder shared with the collector and the age key of support."""

    store: DiagnosticsStore
    recipient: str


class PackageRequest(BaseModel):
    approved_index_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="SHA-256 of the INDEX.json the operator reviewed"
    )


def _support(request: Request) -> SupportDiagnostics:
    configured: SupportDiagnostics | None = getattr(request.app.state, "support", None)
    if configured is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "diagnostics are not configured")
    return configured


def _status(support: SupportDiagnostics, ident: str) -> str:
    try:
        found = support.store.status(ident)
    except DiagnosticsError:
        found = "unknown"
    if found == "unknown":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no diagnostic package {ident}")
    return found


def _journal(request: Request, action: str, detail: dict[str, Any]) -> None:
    journal: Any = getattr(request.app.state, "journal", None)
    actor = caller(request).actor
    if journal is not None:
        journal.append(actor, action, detail)
    security_event(request, action, actor, "succeeded", detail)


@router.post(
    "/diagnostics",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask the collector for a diagnostic package; it is reviewed before anything leaves",
    dependencies=[Depends(require_perm("support.diagnose"))],
)
def request_diagnostics(request: Request) -> dict[str, str]:
    support = _support(request)
    ident = support.store.request(caller(request).actor)
    _journal(request, "support.diagnostics_requested", {"id": ident})
    return {"id": ident, "status": "collecting"}


@router.get(
    "/diagnostics/{diagnostics_id}",
    summary="The preview in clear: the index and every file, exactly as they would leave",
    dependencies=[Depends(require_perm("support.diagnose"))],
)
def preview(request: Request, diagnostics_id: str) -> dict[str, Any]:
    support = _support(request)
    if _status(support, diagnostics_id) == "collecting":
        return {"id": diagnostics_id, "status": "collecting"}
    try:
        found = support.store.load(diagnostics_id)
    except DiagnosticsError as broken:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(broken)) from None
    index = json.loads(found.index)
    scrubbed = {entry["name"]: entry["scrubbed"] for entry in index["files"]}
    return {
        "id": diagnostics_id,
        "status": "ready",
        "index_sha256": found.index_sha256,
        "index": index,
        "files": [
            {
                "name": name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "scrubbed": scrubbed[name],
                "content": data.decode("utf-8", errors="replace"),
            }
            for name, data in sorted(found.files.items())
        ],
    }


@router.post(
    "/diagnostics/{diagnostics_id}/package",
    summary="Encrypt the reviewed preview for support (age); only for the approved index",
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "the package, encrypted"}
    },
    dependencies=[Depends(require_perm("support.package"))],
)
def package(request: Request, diagnostics_id: str, body: PackageRequest) -> Response:
    support = _support(request)
    if _status(support, diagnostics_id) == "collecting":
        raise HTTPException(status.HTTP_409_CONFLICT, "the preview is still being collected")
    try:
        found = support.store.load(diagnostics_id)
        encrypted = build_package(found, body.approved_index_sha256, support.recipient)
    except DiagnosticsError as refused:
        actor = caller(request).actor
        detail = {"id": diagnostics_id, "reason": str(refused)[:200]}
        security_event(request, "support.package_refused", actor, "refused", detail)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(refused)) from None
    _journal(
        request,
        "support.package_built",
        {
            "id": diagnostics_id,
            "index": found.index_sha256,
            "package_sha256": hashlib.sha256(encrypted).hexdigest(),
        },
    )
    name = f"argos-diagnostics-{diagnostics_id}.tar.gz.age"
    return Response(
        encrypted,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
