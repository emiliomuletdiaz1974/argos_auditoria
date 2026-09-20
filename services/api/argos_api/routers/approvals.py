"""Approvals: what this person has pending to approve, across campaigns (ARG-075)."""

from fastapi import APIRouter, Depends

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import Page, Paging, pending

router = APIRouter(prefix="/approvals", tags=["approvals"], route_class=CoreRoute)


@router.get(
    "",
    summary="Control points awaiting this person",
    dependencies=[Depends(require_perm("approvals.read"))],
)
def pending_approvals(paging: Paging) -> Page:
    pending("the pending approvals")
