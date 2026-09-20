"""Assistant: the console question, answered by the AI gateway with its citations (ARG-078)."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from argos_api.http import pending

router = APIRouter(prefix="/assistant", tags=["assistant"])


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    campaign_id: str | None = None


@router.post("/ask", summary="Ask the assistant; it answers with citations or refuses")
def ask(body: Question) -> dict[str, Any]:
    pending("the assistant")
