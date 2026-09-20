"""The only open route of the v1: refreshing the console session (ADR-0013, PKCE)."""

from typing import Any

from fastapi import APIRouter

from argos_api.http import pending

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/refresh", summary="Exchange the refresh cookie for an access token")
def refresh() -> dict[str, Any]:
    pending("the session refresh")
