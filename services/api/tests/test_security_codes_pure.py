"""The refusals of folder 12 (security tests) answer a stable code and Spanish (ARG-071).

Who may call, with which role, with which second factor, with which cursor and idempotency key,
and where a webhook may point: each refusal says so with its own `code`, so the front end can tell
an expired session from a missing role without reading the text.
"""

import datetime as dt
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.errors import ApiError, ErrorCode
from argos_api.paging import page_request
from argos_api.routers.session import SESSION_HEADER
from argos_api.webhooks.destination import DestinationRefusedError, check_destination
from argos_auth import AuthError, Identity, JwtValidator

BEARER = {"Authorization": "Bearer a-token"}


class Holding:
    def __init__(
        self, roles: set[str], amr: set[str] | None = None, sid: str | None = None
    ) -> None:
        self._identity = Identity(
            sub="someone",
            name="Someone",
            roles=frozenset(roles),
            amr=frozenset(amr or {"pwd", "otp"}),
            sid=sid,
        )

    def validate(self, token: str) -> Identity:
        return self._identity


class Refusing:
    def validate(self, token: str) -> Identity:
        raise AuthError("invalid token: InvalidSignatureError")


class AllClosed:
    def close(self, sid: str, until: dt.datetime) -> None: ...

    def is_closed(self, sid: str) -> bool:
        return True


def _client(validator: object | None, **kwargs: Any) -> TestClient:
    return TestClient(create_app(cast(JwtValidator, validator), **kwargs))


def _problem(answer: Any, status: int, code: str) -> dict[str, Any]:
    body: dict[str, Any] = answer.json()
    assert answer.status_code == status, body
    assert body["code"] == code, body
    return body


# ---------- authentication ----------


def test_no_token_is_token_missing() -> None:
    answer = _client(Holding({"dpo_reviewer"})).get(f"{API_PREFIX}/campaigns")
    body = _problem(answer, 401, "token_missing")
    assert body["detail"] == "Falta el token de acceso."
    assert answer.headers["WWW-Authenticate"] == "Bearer"


def test_a_false_token_is_token_invalid() -> None:
    answer = _client(Refusing()).get(f"{API_PREFIX}/campaigns", headers=BEARER)
    body = _problem(answer, 401, "token_invalid")
    assert body["detail"] == "El token de acceso no es válido o ha caducado."


def test_without_a_validator_the_api_says_so() -> None:
    answer = _client(None).get(f"{API_PREFIX}/campaigns", headers=BEARER)
    _problem(answer, 401, "auth_not_configured")


def test_a_closed_session_is_session_closed() -> None:
    client = _client(Holding({"dpo_reviewer"}, sid="s-1"), closed_sessions=AllClosed())
    body = _problem(client.get(f"{API_PREFIX}/campaigns", headers=BEARER), 401, "session_closed")
    assert body["detail"] == "La sesión se cerró: vuelva a iniciarla."


def test_a_token_without_an_argos_role_is_role_missing() -> None:
    answer = _client(Holding({"offline_access"})).get(f"{API_PREFIX}/campaigns", headers=BEARER)
    _problem(answer, 403, "role_missing")


# ---------- permissions ----------


def test_an_auditor_creating_a_campaign_is_permission_denied() -> None:
    answer = _client(Holding({"read_only_auditor"})).post(
        f"{API_PREFIX}/campaigns", json={}, headers=BEARER
    )
    body = _problem(answer, 403, "permission_denied")
    assert body["detail"] == "Su rol no permite esta acción (campaigns.create)."


def test_planning_and_approving_in_one_token_is_roles_incompatible() -> None:
    answer = _client(Holding({"campaign_manager", "dpo_reviewer"})).get(
        f"{API_PREFIX}/campaigns", headers=BEARER
    )
    body = _problem(answer, 403, "roles_incompatible")
    assert "dos personas" in body["detail"]


def test_deciding_without_a_second_factor_is_second_factor_required() -> None:
    answer = _client(Holding({"dpo_reviewer"}, amr={"pwd"})).post(
        f"{API_PREFIX}/campaigns/{uuid4()}/gates/start/approve", json={}, headers=BEARER
    )
    body = _problem(answer, 401, "second_factor_required")
    assert body["detail"] == "Esta acción exige iniciar sesión con segundo factor."
    assert "insufficient_user_authentication" in answer.headers["WWW-Authenticate"]


# ---------- cursor ----------


def test_a_tampered_cursor_is_cursor_invalid() -> None:
    with pytest.raises(ApiError) as refused:
        page_request(cursor="no-es-un-cursor", limit=10)
    assert refused.value.status_code == 400
    assert refused.value.code == ErrorCode.CURSOR_INVALID
    assert refused.value.detail == "El cursor no es válido: pida la primera página de nuevo."


# ---------- idempotency ----------


class Store:
    def __init__(self, error: Exception | None) -> None:
        self._error = error

    def reserve(self, *args: object) -> None:
        if self._error:
            raise self._error


def _idempotent(error: Exception | None, key: str) -> Any:
    client = _client(Holding({"campaign_manager"}))
    client.app.state.idempotency = Store(error)  # type: ignore[attr-defined]
    return client.post(
        f"{API_PREFIX}/campaigns", json={}, headers={**BEARER, "Idempotency-Key": key}
    )


async def test_a_malformed_key_is_idempotency_key_invalid() -> None:
    # The contract checks the header on the routes that declare it; the gate guards every other.
    from types import SimpleNamespace

    from starlette.requests import Request

    from argos_api.core import idempotency_gate

    app = SimpleNamespace(state=SimpleNamespace(idempotency=Store(None)))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/x",
        "headers": [(b"idempotency-key", b"bad key")],
        "app": app,
        "state": {},
    }
    with pytest.raises(ApiError) as refused:
        await idempotency_gate(Request(scope))
    assert refused.value.status_code == 400
    assert refused.value.code == ErrorCode.IDEMPOTENCY_KEY_INVALID


@pytest.mark.parametrize(
    ("error", "code", "detail"),
    [
        (
            "conflict",
            "idempotency_key_reused",
            "La clave de idempotencia k-1 ya se usó con otra petición.",
        ),
        (
            "progress",
            "idempotency_in_progress",
            "La petición con la clave de idempotencia k-1 aún está en curso.",
        ),
    ],
)
def test_a_reused_or_running_key_is_coded(error: str, code: str, detail: str) -> None:
    from argos_api.core import IdempotencyConflictError, IdempotencyInProgressError

    raised = IdempotencyConflictError() if error == "conflict" else IdempotencyInProgressError()
    body = _problem(_idempotent(raised, "k-1"), 409, code)
    assert body["detail"] == detail


# ---------- session routes ----------


def test_a_session_route_without_its_header_is_session_header_missing() -> None:
    answer = _client(Holding({"dpo_reviewer"})).post(f"{API_PREFIX}/auth/refresh")
    body = _problem(answer, 403, "session_header_missing")
    assert SESSION_HEADER in body["detail"]


def test_a_refresh_without_cookie_is_session_cookie_missing() -> None:
    answer = _client(Holding({"dpo_reviewer"})).post(
        f"{API_PREFIX}/auth/refresh", headers={SESSION_HEADER: "1"}
    )
    _problem(answer, 401, "session_cookie_missing")


def test_a_refused_refresh_is_session_refused_without_the_realm_text() -> None:
    async def refuse(token: str) -> dict[str, Any]:
        raise PermissionError("invalid_grant: Token is not active")

    client = _client(Holding({"dpo_reviewer"}), refresher=refuse)
    client.cookies.set("argos_refresh", "r")
    answer = client.post(f"{API_PREFIX}/auth/refresh", headers={SESSION_HEADER: "1"})
    body = _problem(answer, 401, "session_refused")
    assert "Token is not active" not in body["detail"]


def test_a_refused_sign_in_is_sign_in_refused() -> None:
    async def refuse(code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
        raise PermissionError("invalid_grant")

    client = _client(Holding({"dpo_reviewer"}), code_exchanger=refuse)
    answer = client.post(
        f"{API_PREFIX}/auth/session",
        json={"code": "c", "code_verifier": "v" * 43, "redirect_uri": "http://x/callback"},
        headers={SESSION_HEADER: "1"},
    )
    _problem(answer, 401, "sign_in_refused")


# ---------- webhooks ----------


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://itsm.example/hook", "not_https"),
        ("https:///hook", "no_host"),
        ("https://api/hook", "appliance_service"),
        ("https://nowhere.invalid/hook", "unresolvable"),
        ("https://intranet.example/hook", "private_address"),
    ],
)
def test_every_refused_destination_says_why(url: str, reason: str) -> None:
    def resolve(host: str) -> list[str]:
        if host == "nowhere.invalid":
            return []
        return ["10.0.0.7"]

    with pytest.raises(DestinationRefusedError) as refused:
        check_destination(url, resolve=resolve, allowed=())
    assert refused.value.reason == reason


def test_a_webhook_to_an_internal_address_is_webhook_target_not_allowed() -> None:
    client = _client(Holding({"platform_admin"}), webhook_resolve=lambda host: ["10.0.0.7"])
    answer = client.post(
        f"{API_PREFIX}/webhooks",
        json={
            "url": "https://intranet.example/hook",
            "events": ["finding_opened"],
            "secret": "s" * 16,
        },
        headers=BEARER,
    )
    body = _problem(answer, 422, "webhook_target_not_allowed")
    assert "dirección privada o reservada" in body["detail"]
