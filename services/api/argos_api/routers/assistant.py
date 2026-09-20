"""Assistant: the console question, answered by the AI gateway with its citations (ARG-078)."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import pending

router = APIRouter(prefix="/assistant", tags=["assistant"], route_class=CoreRoute)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    campaign_id: str | None = None


@router.post(
    "/ask",
    summary="Ask the assistant; it answers with citations or refuses",
    dependencies=[Depends(require_perm("assistant.ask"))],
)
def ask(body: Question) -> dict[str, Any]:
    pending("the assistant")
