"""Systems: the catalogue of what ARGOS has discovered (ARG-073)."""

from fastapi import APIRouter, Depends

from argos_api.authz import require_perm
from argos_api.http import Page, Paging, pending

router = APIRouter(prefix="/systems", tags=["systems"])


@router.get(
    "", summary="List the registered systems", dependencies=[Depends(require_perm("systems.read"))]
)
def list_systems(paging: Paging) -> Page:
    pending("the system catalogue")
