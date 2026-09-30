"""C-03 · the front end lives on its own origin, on another site (desviación ARG-073, DP-19).

Only the origins the installer lists may change anything from a browser: `_same_origin` lets them
through, CORS answers them and nobody else, and the refresh cookie crosses sites (`SameSite=None`).
Because that cookie now travels to another site, the session routes also ask for a header of
their own, which no page can send without a CORS preflight the API grants only to those origins.
"""

from typing import Any, cast

from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.routers.session import SESSION_HEADER
from argos_auth import Identity, JwtValidator

FRONT = "https://front.example"
OTHER = "https://attacker.example"
API = "https://api.hospital.example"
MANAGER = {"Authorization": "Bearer manager"}
SESSION_BODY = {"code": "c", "code_verifier": "v" * 43, "redirect_uri": f"{FRONT}/callback"}


class Manager:
    def validate(self, token: str) -> Identity:
        return Identity(
            sub="m", name="m", roles=frozenset({"campaign_manager"}), amr=frozenset({"pwd"})
        )


async def _exchange(code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
    return {"access_token": "access", "expires_in": 300, "refresh_token": "the-refresh"}


def _client(*origins: str) -> TestClient:
    app = create_app(
        cast(JwtValidator, Manager()), code_exchanger=_exchange, frontend_origins=origins
    )
    return TestClient(app, base_url=API)


# ---------- the origin check ----------


def test_a_listed_origin_may_send_a_mutation() -> None:
    answer = _client(FRONT).post(
        f"{API_PREFIX}/webhooks", json={}, headers={**MANAGER, "Origin": FRONT}
    )
    assert "another origin" not in answer.text


def test_an_origin_that_is_not_listed_is_still_refused() -> None:
    answer = _client(FRONT).post(
        f"{API_PREFIX}/webhooks", json={}, headers={**MANAGER, "Origin": OTHER}
    )
    assert answer.status_code == 403
    assert "another origin" in answer.text


def test_a_listed_origin_is_compared_whole_not_as_a_prefix() -> None:
    answer = _client(FRONT).post(
        f"{API_PREFIX}/webhooks",
        json={},
        headers={**MANAGER, "Origin": f"{FRONT}.attacker.example"},
    )
    assert answer.status_code == 403


# ---------- CORS ----------


def test_the_preflight_of_a_listed_origin_is_granted_with_credentials() -> None:
    answer = _client(FRONT).options(
        f"{API_PREFIX}/campaigns",
        headers={
            "Origin": FRONT,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type, idempotency-key",
        },
    )
    assert answer.status_code == 200
    assert answer.headers["access-control-allow-origin"] == FRONT
    assert answer.headers["access-control-allow-credentials"] == "true"
    allowed = answer.headers["access-control-allow-headers"].lower()
    for header in ("authorization", "content-type", "idempotency-key", SESSION_HEADER.lower()):
        assert header in allowed, header


def test_the_preflight_of_another_origin_gets_no_grant() -> None:
    answer = _client(FRONT).options(
        f"{API_PREFIX}/campaigns",
        headers={"Origin": OTHER, "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in answer.headers


def test_an_answer_to_a_listed_origin_lets_it_read_the_step_up_challenge() -> None:
    answer = _client(FRONT).get(f"{API_PREFIX}/campaigns", headers={"Origin": FRONT})
    assert answer.headers["access-control-allow-origin"] == FRONT
    assert "www-authenticate" in answer.headers["access-control-expose-headers"].lower()


def test_without_listed_origins_there_is_no_cors_at_all() -> None:
    answer = _client().get(f"{API_PREFIX}/campaigns", headers={"Origin": FRONT})
    assert "access-control-allow-origin" not in answer.headers


# ---------- the session across sites ----------


def test_with_a_front_end_elsewhere_the_refresh_cookie_crosses_sites() -> None:
    answer = _client(FRONT).post(
        f"{API_PREFIX}/auth/session",
        json=SESSION_BODY,
        headers={"Origin": FRONT, SESSION_HEADER: "1"},
    )
    assert answer.status_code == 200
    cookie = answer.headers["set-cookie"].lower()
    assert "samesite=none" in cookie and "secure" in cookie and "httponly" in cookie


def test_without_a_front_end_elsewhere_the_cookie_stays_strict() -> None:
    answer = _client().post(
        f"{API_PREFIX}/auth/session", json=SESSION_BODY, headers={SESSION_HEADER: "1"}
    )
    assert "samesite=strict" in answer.headers["set-cookie"].lower()


def test_the_session_routes_ask_for_their_header() -> None:
    client = _client(FRONT)
    for path in ("session", "refresh", "logout"):
        answer = client.post(f"{API_PREFIX}/auth/{path}", json=SESSION_BODY)
        assert answer.status_code == 403, path
        assert SESSION_HEADER in answer.json()["detail"], path


def test_logout_deletes_the_cookie_with_the_same_attributes() -> None:
    client = _client(FRONT)
    client.cookies.set("argos_refresh", "the-refresh", path=f"{API_PREFIX}/auth")
    answer = client.post(
        f"{API_PREFIX}/auth/logout", headers={"Origin": FRONT, SESSION_HEADER: "1"}
    )
    assert answer.status_code == 204
    assert "samesite=none" in answer.headers["set-cookie"].lower()
