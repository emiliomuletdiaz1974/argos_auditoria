"""Approvals: what this person has pending to approve, across campaigns (ARG-075)."""

from fastapi import APIRouter

from argos_api.http import Page, Paging, pending

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", summary="Control points awaiting this person")
def pending_approvals(paging: Paging) -> Page:
    pending("the pending approvals")
