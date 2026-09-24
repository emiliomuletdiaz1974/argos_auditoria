"""F09-15 (SEC-058) · a mutation sent by a page of another origin is refused before it runs.

The console lives on the origin of the API (ADR-0013). A browser adds `Origin` to every POST, so
a page elsewhere that got hold of a token cannot make the API change anything; a client without a
browser sends no `Origin` and is judged by its token alone.
"""

from typing import cast

from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_auth import Identity, JwtValidator

MANAGER = {"Authorization": "Bearer manager"}


class Manager:
    def validate(self, token: str) -> Identity:
        return Identity(
            sub="m", name="m", roles=frozenset({"campaign_manager"}), amr=frozenset({"pwd"})
        )


def _client() -> TestClient:
    return TestClient(create_app(cast(JwtValidator, Manager())), base_url="http://127.0.0.1:8000")


def test_a_mutation_from_another_origin_is_refused() -> None:
    answer = _client().post(
        f"{API_PREFIX}/webhooks",
        json={},
        headers={**MANAGER, "Origin": "https://attacker.example"},
    )
    assert answer.status_code == 403
    assert answer.headers["content-type"].startswith("application/problem+json")
    assert "origin" in answer.text


def test_an_opaque_origin_is_another_origin() -> None:
    answer = _client().post(
        f"{API_PREFIX}/webhooks", json={}, headers={**MANAGER, "Origin": "null"}
    )
    assert answer.status_code == 403


def test_the_origin_of_the_console_goes_on_to_the_route() -> None:
    answer = _client().post(
        f"{API_PREFIX}/webhooks", json={}, headers={**MANAGER, "Origin": "http://127.0.0.1:8000"}
    )
    assert answer.status_code != 403 or "origin" not in answer.text


def test_a_client_without_origin_is_judged_by_its_token_alone() -> None:
    answer = _client().post(f"{API_PREFIX}/webhooks", json={}, headers=MANAGER)
    assert "origin" not in answer.text


def test_reading_from_another_origin_is_not_a_mutation() -> None:
    answer = _client().get(f"{API_PREFIX}/nothing", headers={"Origin": "https://attacker.example"})
    assert answer.status_code == 404
