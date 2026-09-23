"""Assistant: the console question, answered by the AI gateway with its citations (ARG-078).

The answer is never a verdict and says so every time. When there is not enough to go on, the
assistant says that instead of guessing (`complete` is false), and when the local model is not
there the route answers 503 with the reason: an assistant that is down does not pretend.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from argos_api.assistant import AssistantClient, AssistantUnavailableError
from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import caller

router = APIRouter(prefix="/assistant", tags=["assistant"], route_class=CoreRoute)
NOTICE = (
    "Texto asistido por el modelo local de ARGOS: no es un veredicto ni sustituye a la revisión."
)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    campaign_id: str | None = None


@router.post(
    "/ask",
    summary="Ask the assistant; it answers with citations or refuses",
    dependencies=[Depends(require_perm("assistant.ask"))],
)
async def ask(request: Request, body: Question) -> dict[str, Any]:
    client: AssistantClient | None = getattr(request.app.state, "assistant", None)
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no assistant attached")
    try:
        answer = await client.ask(body.question, caller(request).actor)
    except AssistantUnavailableError as down:
        raise HTTPException(down.status, down.reason) from None
    return {
        "answer": answer.get("answer", ""),
        "sources": answer.get("sources", []),
        "calls": answer.get("calls", []),
        "complete": bool(answer.get("complete", False)),
        "fragments": answer.get("fragments", []),
        "refused": bool(answer.get("refused", False)),
        "assisted": True,
        "notice": NOTICE,
    }
