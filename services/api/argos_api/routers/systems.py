"""Systems: the catalogue of what ARGOS has discovered (ARG-073)."""

from fastapi import APIRouter

from argos_api.http import Page, Paging, pending

router = APIRouter(prefix="/systems", tags=["systems"])


@router.get("", summary="List the registered systems")
def list_systems(paging: Paging) -> Page:
    pending("the system catalogue")
