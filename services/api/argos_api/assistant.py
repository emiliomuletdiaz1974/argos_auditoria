"""The only service the API calls over the network: the AI gateway (ADR-0012, ARG-078).

The API does not import the AI layer. It sends the question to the gateway and hands back what
came back, marked as assisted text. Whatever goes wrong on the other side becomes a reason the
console can show: the model is not there, the gateway is not reachable, the quota is spent.
"""

from typing import Any

import httpx

ASK_PATH = "/v1/assistant/ask"
TIMEOUT_SECONDS = 120.0


class AssistantUnavailableError(Exception):
    """The assistant cannot answer now; `status` is the HTTP status the API answers with."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class AssistantClient:
    def __init__(
        self,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    async def ask(self, question: str, person: str) -> dict[str, Any]:
        """The gateway's answer; `person` is who asks, so the quota is theirs (SEC-043)."""
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, transport=self._transport, timeout=self._timeout
            ) as client:
                response = await client.post(
                    ASK_PATH, json={"question": question, "person": person}
                )
        except httpx.HTTPError as exc:
            raise AssistantUnavailableError(503, f"the AI gateway is not reachable: {exc}") from exc
        if response.status_code == httpx.codes.OK:
            answer: dict[str, Any] = response.json()
            return answer
        detail = _detail(response)
        if response.status_code in (httpx.codes.SERVICE_UNAVAILABLE, httpx.codes.TOO_MANY_REQUESTS):
            raise AssistantUnavailableError(response.status_code, detail)
        raise AssistantUnavailableError(httpx.codes.BAD_GATEWAY, f"the assistant failed: {detail}")


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))
    except ValueError:
        return response.text
