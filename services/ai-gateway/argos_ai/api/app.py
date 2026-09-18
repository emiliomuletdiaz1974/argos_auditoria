"""The AI gateway as an internal HTTP service (ARG-052).

Two endpoints, as the phase document designs them: `/health` and `/v1/chat_json`, the contract the
other services consume. It is internal on purpose: its only protection in development is the
network, like the NetworkPolicy of the appliance — reachable on the network of the AI layer, never
on the one of the campaign API. The prompt never comes back and is never logged: only its hash.
"""

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from argos_ai.gateway import Gateway, GatewayError, QuotaExceededError
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


def create_app(gateway: Gateway) -> FastAPI:
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
        except QuotaExceededError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except OutputRejectedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except GatewayError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "data": answer.data,
            "prompt_sha256": answer.prompt_sha256,
            "tokens_in": answer.tokens_in,
            "tokens_out": answer.tokens_out,
            "repaired": answer.repaired,
            "substitutions": answer.substitutions,
        }

    return app
