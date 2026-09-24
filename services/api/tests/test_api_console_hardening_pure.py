"""ARG-073/079 · what was left of the API and the console (security review F09-02).

- SEC-031: a webhook cannot point inside the appliance (SSRF), and the inbox keeps the kind of
  error, not the raw text of the other side.
- SEC-041: the session can be closed, and the refresh cookie dies with the browser.
- SEC-045: every free text field has a ceiling.
- SEC-046: the console and the API carry the security headers.
- The refresh a realm refuses is a 401, and a realm that answers HTML does not break the API.
"""

import asyncio
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.keycloak import Keycloak
from argos_api.webhooks.destination import DestinationRefusedError, check_destination
from argos_auth import Identity, JwtValidator

BEARER = {"Authorization": "Bearer token"}


def _public(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _private(_host: str) -> list[str]:
    return ["10.0.4.7"]


# ---------- SEC-031 · webhooks never point inside ----------


@pytest.mark.parametrize(
    "url",
    [
        "http://itsm.example.com/hook",  # not https
        "https://127.0.0.1/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/hook",
        "https://vault:8200/v1/sys",
        "https://localhost/hook",
    ],
)
def test_an_internal_or_plain_destination_is_refused(url: str) -> None:
    with pytest.raises(DestinationRefusedError):
        check_destination(url, resolve=_public)


def test_a_name_that_resolves_inside_is_refused() -> None:
    with pytest.raises(DestinationRefusedError, match="private"):
        check_destination("https://itsm.example.com/hook", resolve=_private)


def test_a_public_destination_is_accepted() -> None:
    check_destination("https://itsm.example.com/hook", resolve=_public)


def test_the_itsm_of_the_client_on_a_private_network_is_allowed_by_configuration() -> None:
    check_destination("https://itsm.hospital.local/hook", resolve=_private, allowed=("10.0.0.0/8",))
    check_destination("https://10.0.4.7/hook", resolve=_private, allowed=("10.0.4.7",))


class Admin:
    def validate(self, token: str) -> Identity:
        return Identity(
            sub="admin",
            name="Admin",
            roles=frozenset({"platform_admin"}),
            amr=frozenset({"pwd", "otp"}),
        )


class Store:
    def write(self, path: str, data: dict[str, Any]) -> None:  # pragma: no cover - never reached
        raise AssertionError("a refused webhook must not store its secret")

    def read(self, path: str) -> dict[str, Any]:  # pragma: no cover
        return {}


@pytest.mark.parametrize(
    "url", ["http://vault:8200", "https://127.0.0.1", "https://169.254.169.254"]
)
def test_subscribing_an_internal_destination_is_a_422(url: str) -> None:
    client = TestClient(create_app(cast(JwtValidator, Admin()), webhook_secrets=Store()))
    response = client.post(
        f"{API_PREFIX}/webhooks",
        json={"url": url, "events": ["finding_opened"], "secret": "s" * 16},
        headers=BEARER,
    )
    assert response.status_code == 422, response.text


# ---------- SEC-041 · a session that closes ----------


def _session_client(revoked: list[str], refuse: bool = False) -> TestClient:
    async def exchange(code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        return {"access_token": "a", "refresh_token": "r", "refresh_expires_in": 1800}

    async def refresh(token: str) -> dict[str, Any]:
        if refuse:
            raise PermissionError("invalid_grant")
        return {"access_token": "a2"}

    async def revoke(token: str) -> None:
        revoked.append(token)

    return TestClient(
        create_app(code_exchanger=exchange, refresher=refresh, session_revoker=revoke),
        base_url="https://testserver",
    )


def test_the_refresh_cookie_lives_only_as_long_as_the_browser() -> None:
    answer = _session_client([]).post(
        f"{API_PREFIX}/auth/session",
        json={"code": "c", "code_verifier": "v" * 43, "redirect_uri": "https://x/cb"},
    )
    cookie = answer.headers["set-cookie"].lower()
    assert "max-age" not in cookie and "expires" not in cookie


def test_logout_revokes_the_refresh_and_deletes_the_cookie() -> None:
    revoked: list[str] = []
    client = _session_client(revoked)
    client.cookies.set("argos_refresh", "the-refresh", path=f"{API_PREFIX}/auth")
    answer = client.post(f"{API_PREFIX}/auth/logout")
    assert answer.status_code == 204
    assert revoked == ["the-refresh"]
    cookie = answer.headers["set-cookie"].lower()
    assert "argos_refresh=" in cookie and ("max-age=0" in cookie or "expires=" in cookie)


def test_a_refresh_the_realm_refuses_is_a_401() -> None:
    client = _session_client([], refuse=True)
    client.cookies.set("argos_refresh", "stale", path=f"{API_PREFIX}/auth")
    answer = client.post(f"{API_PREFIX}/auth/refresh")
    assert answer.status_code == 401
    assert answer.headers["content-type"].startswith("application/problem+json")


def test_a_realm_that_answers_html_is_a_refusal_not_a_crash() -> None:
    def html(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    realm = Keycloak("https://kc/realms/argos", transport=httpx.MockTransport(html))
    with pytest.raises(PermissionError):
        asyncio.run(realm.refresh("r"))


def test_the_realm_is_asked_to_end_the_session() -> None:
    seen: list[httpx.Request] = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    realm = Keycloak("https://kc/realms/argos", transport=httpx.MockTransport(ok))
    asyncio.run(realm.logout("the-refresh"))
    assert seen[0].url.path.endswith("/protocol/openid-connect/logout")
    assert b"refresh_token=the-refresh" in seen[0].content


# ---------- SEC-046 · security headers everywhere ----------


EXPECTED = {
    "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
}


def test_the_console_and_the_api_carry_the_security_headers(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    client = TestClient(create_app(cast(JwtValidator, Admin()), console=tmp_path))
    for path in ("/", "/findings/x", f"{API_PREFIX}/campaigns", "/health"):
        headers = client.get(path).headers
        for name, value in EXPECTED.items():
            assert headers.get(name) == value, (path, name)


# ---------- SEC-045 · every free text has a ceiling ----------


class Roles:
    def __init__(self, *roles: str) -> None:
        self._roles = frozenset(roles)

    def validate(self, token: str) -> Identity:
        return Identity(
            sub="someone", name="Someone", roles=self._roles, amr=frozenset({"pwd", "otp"})
        )


@pytest.mark.parametrize(
    ("role", "path", "body"),
    [
        ("platform_admin", f"/credentials/{uuid4()}/revoke", {"reason": "x" * 5000}),
        ("dpo_reviewer", "/inventory/review-queue/k-1", {"decision": "accept", "note": "x" * 5000}),
        (
            "campaign_manager",
            f"/synthetic/{uuid4()}/confirm-exercise",
            {
                "right": "x" * 5000,
                "requested_at": "2026-01-01T00:00:00+00:00",
                "answered_at": "2026-01-02T00:00:00+00:00",
            },
        ),
    ],
)
def test_a_text_field_without_a_ceiling_is_refused(
    role: str, path: str, body: dict[str, Any]
) -> None:
    client = TestClient(create_app(cast(JwtValidator, Roles(role))))
    assert client.post(f"{API_PREFIX}{path}", json=body, headers=BEARER).status_code == 422


def test_an_idempotency_key_of_kilobytes_is_refused() -> None:
    client = TestClient(create_app(cast(JwtValidator, Roles("campaign_manager"))))
    response = client.post(
        f"{API_PREFIX}/campaigns",
        json={"name": "Campaña", "scope": {}},
        headers={**BEARER, "Idempotency-Key": "k" * 5000},
    )
    assert response.status_code == 422
