"""Systems: the catalogue of what ARGOS has discovered (ARG-073)."""

from fastapi import APIRouter, Depends, Request

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import database
from argos_api.paging import Page, Paging, paginate
from argos_inventory.catalog.views import systems

router = APIRouter(prefix="/systems", tags=["systems"], route_class=CoreRoute)


@router.get(
    "", summary="List the registered systems", dependencies=[Depends(require_perm("systems.read"))]
)
def list_systems(request: Request, paging: Paging) -> Page:
    # One row more than asked: that is how the page knows whether there is a next one.
    rows = systems(database(request), paging.limit + 1, paging.position)
    return paginate(rows, paging.limit)
