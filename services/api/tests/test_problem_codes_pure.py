"""Every error of the API carries a stable `code` and speaks Spanish to the person (ARG-071).

The front end decides on `code`, which never changes with the wording; `title` and `detail` are
what it shows. Logs and domain exceptions stay in English (ADR-0005): only the answer changes.
"""

from typing import cast

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.errors import TITLES, ApiError, ErrorCode
from argos_auth import Identity, JwtValidator

BEARER = {"Authorization": "Bearer a-token"}
SNAKE = r"^[a-z][a-z0-9_]*$"

# The codes are the contract: renaming or removing one breaks every front end that relies on it.
# Adding one means adding it here, on purpose.
FROZEN = {
    "bad_request",
    "unauthenticated",
    "forbidden",
    "not_found",
    "conflict",
    "unprocessable",
    "too_many_requests",
    "internal_error",
    "not_implemented",
    "service_unavailable",
    "route_not_found",
    "invalid_request",
    "invalid_value",
    "store_unavailable",
    "origin_not_allowed",
    "token_missing",
    "token_invalid",
    "auth_not_configured",
    "session_closed",
    "role_missing",
    "permission_denied",
    "roles_incompatible",
    "second_factor_required",
    "cursor_invalid",
    "idempotency_key_invalid",
    "idempotency_key_reused",
    "idempotency_in_progress",
    "session_header_missing",
    "session_cookie_missing",
    "session_refused",
    "sign_in_refused",
    "webhook_target_not_allowed",
}


class Manager:
    def validate(self, token: str) -> Identity:
        return Identity(
            sub="someone",
            name="Someone",
            roles=frozenset({"campaign_manager"}),
            amr=frozenset({"pwd", "otp"}),
        )


def _client(**kwargs: object) -> TestClient:
    app = create_app(cast(JwtValidator, Manager()), **kwargs)  # type: ignore[arg-type]

    def data_error() -> None:
        raise psycopg.DataError("invalid input syntax for type timestamp: host db-1")

    def store_error() -> None:
        raise psycopg.OperationalError("connection to server at 10.0.0.5 failed")

    def bare_conflict() -> None:
        raise HTTPException(409, "a legacy message")

    def coded() -> None:
        raise ApiError(409, ErrorCode.CONFLICT, "El estado no lo permite.")

    for path, endpoint in (
        ("/_t/data", data_error),
        ("/_t/store", store_error),
        ("/_t/bare", bare_conflict),
        ("/_t/coded", coded),
    ):
        app.add_api_route(path, endpoint)
    return TestClient(app, raise_server_exceptions=False)


def test_the_catalogue_of_codes_is_stable() -> None:
    assert {c.value for c in ErrorCode} == FROZEN


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 429, 500, 501, 503])
def test_every_status_has_a_spanish_title(status: int) -> None:
    assert TITLES[status][0].isupper()
    assert TITLES[status] not in {"error", "conflict", "not found", "forbidden"}


def test_an_unknown_route_answers_a_coded_spanish_404() -> None:
    answer = _client().get(f"{API_PREFIX}/nada-por-aqui", headers=BEARER)
    body = answer.json()
    assert answer.status_code == 404
    assert body["code"] == "route_not_found"
    assert body["title"] == "No encontrado"
    assert body["detail"] == "La ruta no existe."


def test_an_invalid_body_names_the_field_and_the_reason_in_spanish() -> None:
    answer = _client().post(f"{API_PREFIX}/campaigns", json={}, headers=BEARER)
    body = answer.json()
    assert answer.status_code == 422
    assert body["code"] == "invalid_request"
    assert body["title"] == "Petición inválida"
    assert "body." in body["detail"]
    assert "campo obligatorio" in body["detail"]
    assert "Field required" not in body["detail"]


def test_an_unreadable_value_is_a_coded_400_without_the_driver_message() -> None:
    body = _client().get("/_t/data").json()
    assert body["status"] == 400
    assert body["code"] == "invalid_value"
    assert body["detail"] == "Un valor de la petición no es válido."
    assert "db-1" not in str(body)


def test_a_store_failure_is_a_coded_503_without_the_host() -> None:
    body = _client().get("/_t/store").json()
    assert body["status"] == 503
    assert body["code"] == "store_unavailable"
    assert body["title"] == "Servicio no disponible"
    assert "10.0.0.5" not in str(body)


def test_an_uncoded_exception_gets_the_generic_code_of_its_status() -> None:
    body = _client().get("/_t/bare").json()
    assert body["code"] == "conflict"
    assert body["title"] == "Conflicto"


def test_a_coded_error_keeps_its_code_and_detail() -> None:
    body = _client().get("/_t/coded").json()
    assert body == {
        "type": "about:blank",
        "code": "conflict",
        "title": "Conflicto",
        "status": 409,
        "detail": "El estado no lo permite.",
        "instance": "/_t/coded",
    }


def test_a_change_from_another_origin_is_coded() -> None:
    answer = _client().post(
        f"{API_PREFIX}/webhooks",
        json={},
        headers={**BEARER, "Origin": "https://attacker.example"},
    )
    body = answer.json()
    assert answer.status_code == 403
    assert body["code"] == "origin_not_allowed"
    assert body["detail"] == "Cambio enviado desde otro origen."


def test_every_code_is_snake_case() -> None:
    import re

    assert all(re.match(SNAKE, c.value) for c in ErrorCode)
