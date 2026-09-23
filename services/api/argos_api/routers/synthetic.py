"""The synthetic subject: what the client confirms it did, step by step (ADR-0008, ARG-075).

ARGOS never injects anything. The DPO authorises an injection point —with the procedure that
undoes it— through the campaign it belongs to, and the client confirms each step here: that it
injected the subject, that it exercised a right, and that it put the source back as it was. Each
confirmation is an entry of the journal with a name behind it.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import caller, database
from argos_challenges.synthetic import (
    SyntheticError,
    confirm_exercise,
    confirm_injection,
    confirm_revert,
)

router = APIRouter(prefix="/synthetic", tags=["synthetic"], route_class=CoreRoute)


class Exercise(BaseModel):
    right: str = Field(default="erasure", min_length=1, description="the right exercised")


DEFAULT_EXERCISE = Exercise()


def _confirmed(step: Any, *args: Any) -> None:
    try:
        step(*args)
    except SyntheticError as refused:
        raise HTTPException(status.HTTP_409_CONFLICT, str(refused)) from None


@router.post(
    "/{injection_id}/confirm-injection",
    summary="The client says it injected the subject at the authorised point",
    dependencies=[Depends(require_perm("synthetic.confirm"))],
)
def injected(request: Request, injection_id: UUID) -> dict[str, str]:
    _confirmed(confirm_injection, database(request), str(injection_id), caller(request).actor)
    return {"injection_id": str(injection_id), "state": "injected"}


@router.post(
    "/{injection_id}/confirm-exercise",
    summary="The client says the subject exercised a right",
    dependencies=[Depends(require_perm("synthetic.confirm"))],
)
def exercised(
    request: Request,
    injection_id: UUID,
    body: Annotated[Exercise, Body()] = DEFAULT_EXERCISE,
) -> dict[str, str]:
    _confirmed(
        confirm_exercise, database(request), str(injection_id), body.right, caller(request).actor
    )
    return {"injection_id": str(injection_id), "state": "exercised"}


@router.post(
    "/{injection_id}/confirm-revert",
    summary="The client says it put the source back as it was",
    dependencies=[Depends(require_perm("synthetic.confirm"))],
)
def reverted(request: Request, injection_id: UUID) -> dict[str, str]:
    _confirmed(confirm_revert, database(request), str(injection_id), caller(request).actor)
    return {"injection_id": str(injection_id), "state": "reverted"}
