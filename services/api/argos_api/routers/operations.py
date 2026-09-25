"""ARG-092/099 · the operation screen: the eight lights, the active alerts and their runbooks.

`GET /operations/status` and `GET /operations/runbooks/{runbook_id}` are read by the administrator
and the auditor (`operations.read`). Alertmanager delivers the alerts on `POST
/internal/alertmanager`, outside the contract of the people: a machine route with its own token.
"""

import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import database
from argos_api.operations import Alerts, Metrics, lights, runbook_text
from argos_api.sizing import size_limits
from argos_common.capacity import history, usage

router = APIRouter(prefix="/operations", tags=["operations"], route_class=CoreRoute)
internal = APIRouter()


def _metrics(request: Request) -> Metrics | None:
    return getattr(request.app.state, "operations_metrics", None)


def _alerts(request: Request) -> Alerts | None:
    return getattr(request.app.state, "operations_alerts", None)


@router.get(
    "/status",
    summary="The eight lights of the appliance and the active alerts, each with its runbook",
    dependencies=[Depends(require_perm("operations.read"))],
)
def operation_status(request: Request) -> dict[str, Any]:
    metrics, alerts = _metrics(request), _alerts(request)
    return {
        "lights": lights(metrics) if metrics is not None else [],
        "alerts": alerts.active() if alerts is not None else [],
        "measured": metrics is not None,
    }


@router.get(
    "/runbooks/{runbook_id}",
    summary="The text of a runbook of the book of operation, in Markdown",
    dependencies=[Depends(require_perm("operations.read"))],
)
def operation_runbook(request: Request, runbook_id: str) -> dict[str, str]:
    folder = getattr(request.app.state, "runbooks_dir", None)
    text = runbook_text(folder, runbook_id) if folder is not None else None
    if text is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such runbook")
    return {"id": runbook_id, "markdown": text}


@router.get(
    "/capacity",
    summary="Where the appliance stands against its size, and the series of the last 13 months",
    dependencies=[Depends(require_perm("operations.read"))],
)
def operation_capacity(request: Request) -> dict[str, Any]:
    limits = size_limits(request)
    if limits is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the size is not configured")
    dsn = database(request)
    return {"size": limits[0], "usage": usage(dsn, limits[0], limits[1]), "history": history(dsn)}


@internal.post("/internal/alertmanager", include_in_schema=False, status_code=204)
async def alertmanager_webhook(request: Request) -> Response:
    """Alertmanager delivers here, with the token of its configuration as a bearer."""
    expected: str | None = getattr(request.app.state, "alertmanager_token", None)
    alerts = _alerts(request)
    if not expected or alerts is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the alert receiver is closed")
    given = request.headers.get("authorization", "")
    scheme, _, token = given.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not the alertmanager of this appliance")
    notification = await request.json()
    alerts.receive(notification if isinstance(notification, dict) else {})
    return Response(status_code=204)
