"""ARG-086 · asking for an update from the API (F09-10).

The API does not apply anything: it checks the bundle the operator placed in the inbox of the
appliance (the esclusa of ARG-090 brings it on removable media) with the pinned release key, the
same verification the updater does, and queues the request. The updater applies it, with its
reverse plan written first, and leaves every step in the journal and in the security log.
Only `platform_admin`, with the second factor.
"""

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import IdempotencyKey, caller
from argos_updater import UpdateRejectedError, verify_bundle

router = APIRouter(prefix="/system", tags=["system"], route_class=CoreRoute)
BUNDLE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


@dataclass(frozen=True, slots=True)
class UpdateRequests:
    """Where the bundles wait (inbox), where the requests go (queue), what is installed (state)."""

    inbox: Path
    queue: Path
    state: Path
    release_key: bytes

    def installed(self) -> str | None:
        path = self.state / "version"
        return path.read_text(encoding="utf-8").strip() if path.is_file() else None


class UpdateRequest(BaseModel):
    bundle: str = Field(
        pattern=BUNDLE_NAME.pattern, description="folder of the bundle in the inbox"
    )
    allow_downgrade: bool = Field(
        default=False, description="an older version, on purpose; the updater records it"
    )


def _requests(request: Request) -> UpdateRequests:
    configured: UpdateRequests | None = getattr(request.app.state, "updates", None)
    if configured is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "updates are not configured")
    return configured


@router.post(
    "/updates",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Verify an update bundle of the inbox and queue it for the updater",
    dependencies=[Depends(require_perm("system.update"))],
)
def request_update(
    request: Request, body: UpdateRequest, idempotency_key: IdempotencyKey = None
) -> dict[str, Any]:
    updates = _requests(request)
    bundle = updates.inbox / body.bundle
    if not bundle.is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no bundle {body.bundle} in the inbox")
    try:
        verified = verify_bundle(
            bundle, updates.release_key, updates.installed(), body.allow_downgrade
        )
    except UpdateRejectedError as refused:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(refused)) from None
    ident = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    updates.queue.mkdir(parents=True, exist_ok=True)
    temporary = updates.queue / f".{ident}.tmp"
    temporary.write_text(
        json.dumps(
            {
                "bundle": body.bundle,
                "version": verified.version,
                "allow_downgrade": body.allow_downgrade,
                "requested_by": caller(request).actor,
            }
        ),
        encoding="utf-8",
    )
    temporary.replace(updates.queue / f"{ident}.json")
    return {"request": ident, "version": verified.version, "status": "queued"}
