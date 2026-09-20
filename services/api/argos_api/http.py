"""What every resource of the v1 shares: errors, pagination and idempotency (ADR-0012).

Three decisions live here so no router repeats them: errors travel as `application/problem+json`
(RFC 9457), listings paginate by an opaque cursor —never by offset, which shifts under a concurrent
write— and every POST that creates accepts an `Idempotency-Key` so a retry does not create twice.
"""

from typing import Annotated, Any, NoReturn

from fastapi import Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from argos_api.paging import Page, PageRequest, Paging

PROBLEM_MEDIA_TYPE = "application/problem+json"
__all__ = [
    "ERRORS",
    "PROBLEM_MEDIA_TYPE",
    "IdempotencyKey",
    "Page",
    "PageRequest",
    "Paging",
    "Problem",
    "ProblemResponse",
    "pending",
    "problem_response",
]


class Problem(BaseModel):
    """An error as RFC 9457 describes it: the same shape whatever went wrong."""

    type: str = Field(default="about:blank", description="identifier of the kind of problem")
    title: str = Field(description="short human summary, the same for every occurrence")
    status: int = Field(description="HTTP status code")
    detail: str | None = Field(default=None, description="what happened in this occurrence")
    instance: str = Field(description="path where it happened")


class ProblemResponse(JSONResponse):
    media_type = PROBLEM_MEDIA_TYPE


def problem_response(
    request: Request, status_code: int, title: str, detail: str | None
) -> ProblemResponse:
    body = Problem(
        title=title, status=status_code, detail=detail, instance=request.url.path
    ).model_dump()
    return ProblemResponse(status_code=status_code, content=body)


IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        description="key chosen by the client; repeating it returns the first result",
    ),
]

ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"model": Problem, "description": "no valid token"},
    status.HTTP_403_FORBIDDEN: {"model": Problem, "description": "the role does not allow it"},
    status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "it does not exist"},
    status.HTTP_409_CONFLICT: {"model": Problem, "description": "the state does not allow it"},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": Problem, "description": "invalid body"},
}


def pending(what: str) -> NoReturn:
    """The route exists in the contract and its behaviour arrives in its own task of phase 08."""
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"{what} is not implemented yet")
