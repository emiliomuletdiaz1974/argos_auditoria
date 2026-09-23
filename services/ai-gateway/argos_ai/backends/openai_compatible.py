"""The backend that talks to a real server: vLLM in the appliance, llama.cpp in development.

One implementation for both, because both speak the OpenAI-compatible API (ADR-0009). Changing
from one to the other is configuration: `ARGOS_LLM_LOCAL_ENDPOINT` and `ARGOS_LLM_MODEL`.
"""

from typing import Any

import httpx

from .base import Completion

TIMEOUT_SECONDS = 120.0
MAX_ANSWER_TOKENS = 2_048


class OpenAiCompatibleBackend:
    """A chat completion against a local server. No key travels: the server is inside."""

    def __init__(
        self,
        base_url: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        max_tokens: int = MAX_ANSWER_TOKENS,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._client = client
        self._max_tokens = max_tokens

    async def complete(
        self, system: str, user: str, schema: dict[str, object] | None = None
    ) -> Completion:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            # Without a cap one answer can spend the whole daily quota before it is counted.
            "max_tokens": self._max_tokens,
        }
        if schema is not None:
            # Guided decoding when the server supports it; the gateway validates in any case.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": schema, "strict": True},
            }
        owned = self._client is None
        client = self._client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        try:
            response = await client.post(self._url, json=payload)
            response.raise_for_status()
            body = response.json()
        finally:
            if owned:
                await client.aclose()
        usage = body.get("usage") or {}
        return Completion(
            text=str(body["choices"][0]["message"]["content"]),
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
        )
