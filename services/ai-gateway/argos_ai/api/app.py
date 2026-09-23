"""The AI gateway as an internal HTTP service (ARG-052, ARG-058).

Three endpoints: `/health`, `/v1/chat_json`, the contract the other services consume, and
`/v1/assistant/ask`, where the console assistant runs with its four closed tools. The agent lives
here and not in the API on purpose (ADR-0012): what the model says is handled inside this
perimeter, whose database role has no privilege over a verdict, and only its result travels.

It is internal on purpose: its only protection in development is the network, like the
NetworkPolicy of the appliance — reachable on the network of the AI layer, where the v1 API asks it
by HTTP, and never on the one of the campaign engine. The prompt never comes back and is never
logged: only its hash.
"""

from collections.abc import Mapping
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from argos_ai.assistant.agent import AssistantError, ask
from argos_ai.assistant.tools import Tool
from argos_ai.gateway import Gateway, GatewayError, ModelUnavailableError, QuotaExceededError
from argos_ai.guardrails import OutputRejectedError

SERVICE_NAME = "argos-ai-gateway"
DEV_HOST = "127.0.0.1"
DEV_PORT = 8005


class ChatJsonRequest(BaseModel):
    service: str = Field(min_length=1, max_length=40)
    system: str = Field(min_length=1)
    user: str = Field(min_length=1)
    json_schema: dict[str, Any] = Field(alias="schema")
    priority: Literal["interactive", "batch"] = "batch"


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    # Who asks, as the API authenticated them: the assistant's quota is per person (SEC-043).
    person: str = Field(pattern=r"^user:[^\s]{1,200}$")


def _refusal(exc: GatewayError) -> HTTPException:
    """The same error, the same status, whichever endpoint met it."""
    if isinstance(exc, QuotaExceededError):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, ModelUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def create_app(gateway: Gateway, tools: Mapping[str, Tool] | None = None) -> FastAPI:
    app = FastAPI(title="ARGOS AI gateway", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME}

    @app.post("/v1/chat_json")
    async def chat_json(request: ChatJsonRequest) -> dict[str, Any]:
        try:
            answer = await gateway.chat_json(
                request.service,
                request.system,
                request.user,
                request.json_schema,
                priority=request.priority,
            )
        except OutputRejectedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except GatewayError as exc:
            raise _refusal(exc) from exc
        return {
            "data": answer.data,
            "prompt_sha256": answer.prompt_sha256,
            "tokens_in": answer.tokens_in,
            "tokens_out": answer.tokens_out,
            "repaired": answer.repaired,
            "substitutions": answer.substitutions,
        }

    @app.post("/v1/assistant/ask")
    async def assistant(request: Question) -> dict[str, Any]:
        if tools is None:
            raise HTTPException(status_code=503, detail="this gateway has no assistant tools")
        try:
            answer = await ask(request.question, gateway, tools, person=request.person)
        except OutputRejectedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except AssistantError as exc:  # it quoted what it did not consult: not an answer
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except GatewayError as exc:
            raise _refusal(exc) from exc
        return {
            "answer": answer.answer,
            "sources": answer.sources,
            "complete": answer.complete,
            "calls": answer.calls,
            "fragments": answer.fragments,
            "refused": answer.refused,
            "assisted": True,
        }

    return app
