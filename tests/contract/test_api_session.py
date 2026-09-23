"""ADR-0013 · the console session on the side of the API: the refresh token never reaches the page.

The console hands the code and its PKCE verifier to `/api/v1/auth/session`; the API exchanges them,
keeps the refresh token in an HttpOnly cookie that only `/api/v1/auth` (refresh and logout) sees,
and answers with the access token alone.
"""

from typing import Any

from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app

SESSION = f"{API_PREFIX}/auth/session"
REDIRECT = "https://argos.appliance.example/callback"


def _client(seen: list[tuple[str, str, str]]) -> TestClient:
    async def exchange(code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        seen.append((code, verifier, redirect_uri))
        return {"access_token": "access", "expires_in": 300, "refresh_token": "the-refresh"}

    return TestClient(create_app(code_exchanger=exchange))


def test_the_code_becomes_an_access_token_and_a_cookie_the_page_cannot_read() -> None:
    seen: list[tuple[str, str, str]] = []
    answer = _client(seen).post(
        SESSION,
        json={"code": "the-code", "code_verifier": "v" * 43, "redirect_uri": REDIRECT},
    )
    assert answer.status_code == 200
    assert answer.json()["access_token"] == "access"
    assert "the-refresh" not in answer.text, "the refresh token travels only in the cookie"
    assert seen == [("the-code", "v" * 43, REDIRECT)]

    cookie = answer.headers["set-cookie"]
    assert "argos_refresh=the-refresh" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie
    assert "samesite=strict" in cookie.lower()
    assert f"Path={API_PREFIX}/auth" in cookie  # the refresh and the logout, nothing else


def test_a_verifier_that_is_not_pkce_is_refused() -> None:
    answer = _client([]).post(
        SESSION, json={"code": "the-code", "code_verifier": "short", "redirect_uri": REDIRECT}
    )
    assert answer.status_code == 422


def test_without_an_exchanger_the_api_says_so() -> None:
    answer = TestClient(create_app()).post(
        SESSION, json={"code": "c", "code_verifier": "v" * 43, "redirect_uri": REDIRECT}
    )
    assert answer.status_code == 501
    assert answer.headers["content-type"].startswith("application/problem+json")


def test_a_code_the_identity_provider_refuses_is_a_401() -> None:
    async def refuse(code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        raise PermissionError("invalid_grant")

    answer = TestClient(create_app(code_exchanger=refuse)).post(
        SESSION, json={"code": "c", "code_verifier": "v" * 43, "redirect_uri": REDIRECT}
    )
    assert answer.status_code == 401
