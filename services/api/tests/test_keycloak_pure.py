"""ARG-073 · the API is the one that talks to Keycloak; the console never holds a client secret.

The console brings the authorization code and its verifier, and this exchanges them at the realm
with the public client `argos-console`. What comes back is a token pair: the access token travels
to the console, the refresh token stays in the HttpOnly cookie the API sets.
"""

import json
from typing import Any

import httpx
import pytest

from argos_api.keycloak import CONSOLE_CLIENT, Keycloak


def _realm(answers: list[httpx.Response]) -> tuple[Keycloak, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "url": str(request.url),
                "form": dict(httpx.QueryParams(request.content.decode())),
            }
        )
        return answers.pop(0)

    realm = Keycloak("http://keycloak:8080/realms/argos", transport=httpx.MockTransport(handle))
    return realm, seen


def _tokens() -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps({"access_token": "at", "refresh_token": "rt", "expires_in": 300}),
        headers={"Content-Type": "application/json"},
    )


@pytest.mark.asyncio
async def test_the_code_is_exchanged_with_pkce_and_no_secret() -> None:
    realm, seen = _realm([_tokens()])
    tokens = await realm.exchange("a-code", "a-verifier", "http://127.0.0.1:8000/callback")

    assert tokens["access_token"] == "at"
    assert seen[0]["url"].endswith("/protocol/openid-connect/token")
    form = seen[0]["form"]
    assert form["grant_type"] == "authorization_code"
    assert form["client_id"] == CONSOLE_CLIENT
    assert form["code_verifier"] == "a-verifier"
    assert form["redirect_uri"] == "http://127.0.0.1:8000/callback"
    assert "client_secret" not in form, "the console client is public: it has no secret"


@pytest.mark.asyncio
async def test_a_refused_sign_in_is_a_permission_error_not_a_crash() -> None:
    realm, _ = _realm([httpx.Response(400, json={"error": "invalid_grant"})])
    with pytest.raises(PermissionError, match="invalid_grant"):
        await realm.exchange("used-code", "a-verifier", "http://127.0.0.1:8000/callback")


@pytest.mark.asyncio
async def test_the_refresh_uses_the_refresh_grant() -> None:
    realm, seen = _realm([_tokens()])
    tokens = await realm.refresh("rt")

    assert tokens["refresh_token"] == "rt"
    assert seen[0]["form"]["grant_type"] == "refresh_token"
    assert seen[0]["form"]["refresh_token"] == "rt"


@pytest.mark.asyncio
async def test_an_expired_refresh_is_refused_as_such() -> None:
    realm, _ = _realm([httpx.Response(400, json={"error": "invalid_grant"})])
    with pytest.raises(PermissionError):
        await realm.refresh("an-old-one")
