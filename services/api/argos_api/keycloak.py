"""The realm, from the API: the console never holds a secret (ADR-0013, ARG-073).

The console signs in with PKCE and brings back an authorization code. It is this side that speaks
to Keycloak —with the public client `argos-console`, no client secret anywhere— and it is this side
that keeps the refresh token, in an HttpOnly cookie the browser cannot read. A sign-in the realm
refuses is a `PermissionError`, which the session route turns into a 401 with its reason.
"""

from typing import Any

import httpx

CONSOLE_CLIENT = "argos-console"
TOKEN_ENDPOINT = "/protocol/openid-connect/token"  # noqa: S105 - a path, not a secret
LOGOUT_ENDPOINT = "/protocol/openid-connect/logout"
TIMEOUT = 10.0


class Keycloak:
    """What the API asks of the realm: exchange a code, renew from a refresh token."""

    def __init__(
        self, issuer: str, *, client_id: str = CONSOLE_CLIENT, transport: Any = None
    ) -> None:
        self._url = f"{issuer.rstrip('/')}{TOKEN_ENDPOINT}"
        self._logout_url = f"{issuer.rstrip('/')}{LOGOUT_ENDPOINT}"
        self._client_id = client_id
        self._transport = transport

    async def _tokens(self, form: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT) as client:
            answer = await client.post(self._url, data={**form, "client_id": self._client_id})
        if answer.status_code >= httpx.codes.BAD_REQUEST:
            raise PermissionError(_reason(answer))
        try:
            tokens: dict[str, Any] = answer.json()
        except ValueError as exc:
            raise PermissionError("the realm did not answer with tokens") from exc
        return tokens

    async def exchange(self, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        """The authorization code and the verifier the console kept, for a token pair."""
        return await self._tokens(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            }
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """A new access token from the refresh token of the cookie."""
        return await self._tokens({"grant_type": "refresh_token", "refresh_token": refresh_token})

    async def logout(self, refresh_token: str) -> None:
        """End the session at the realm, so the refresh token is worth nothing (SEC-041)."""
        async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT) as client:
            answer = await client.post(
                self._logout_url,
                data={"client_id": self._client_id, "refresh_token": refresh_token},
            )
        if answer.status_code >= httpx.codes.BAD_REQUEST:
            raise PermissionError(_reason(answer))


def _reason(answer: httpx.Response) -> str:
    """Why the realm refused, whether it answered JSON or not (a proxy may answer HTML)."""
    try:
        body = answer.json()
    except ValueError:
        return f"the realm answered {answer.status_code}"
    return str(body.get("error", answer.status_code)) if isinstance(body, dict) else str(body)
