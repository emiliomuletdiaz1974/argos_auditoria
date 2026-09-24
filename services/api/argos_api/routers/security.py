"""F09-08 · the security log, read by the platform administrator and the auditor.

Who tried what, newest first and paged by cursor. It is a separate chain from the journal of the
product (ADR-0014, DP-14) and nobody can change it through here: there is only a reading.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import database
from argos_api.paging import Page, Paging, paginate
from argos_api.security_events import list_events

router = APIRouter(prefix="/security", tags=["security"], route_class=CoreRoute)


@router.get(
    "/events",
    summary="The security log: authentication, authorisation and signature events",
    dependencies=[Depends(require_perm("security.read"))],
)
def events(request: Request, paging: Paging) -> Page:
    rows = list_events(database(request), paging.limit + 1, paging.position)
    page = paginate(rows, paging.limit, at="at", ident="_order")
    items: list[dict[str, Any]] = [
        {k: v for k, v in item.items() if k != "_order"} for item in page.items
    ]
    return Page(items=items, next=page.next)
