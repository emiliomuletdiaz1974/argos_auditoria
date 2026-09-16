"""ARG-029 · inventory API authentication, depth limit and argument checks without a database."""

import time
from types import SimpleNamespace
from typing import Any

import httpx
import jwt
import pytest
import strawberry
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from strawberry.extensions import QueryDepthLimiter

from argos_auth import ROLES, JwtValidator
from argos_inventory.api.app import create_app
from argos_inventory.api.schema import MAX_QUERY_DEPTH, build_schema
from argos_inventory.graph.store import GraphStore

ISSUER = "http://127.0.0.1:8180/realms/argos"
AUDIENCE = "argos-platform"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
UNREACHABLE = "postgresql://nobody@127.0.0.1:9/none"
TYPENAME = "{ __typename }"


@strawberry.type
class Level:
    name: str

    @strawberry.field
    def next(self) -> "Level":
        return Level(name="deeper")


@strawberry.type
class DeepQuery:
    @strawberry.field
    def level(self) -> Level:
        return Level(name="top")


class FakeKeys:
    def get_signing_key_from_jwt(self, token: str) -> Any:
        return SimpleNamespace(key=KEY.public_key())


def _token(roles: list[str], key: Any = KEY) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u-inventory",
        "iat": now,
        "exp": now + 300,
        "preferred_username": "auditor.test",
        "realm_access": {"roles": roles},
    }
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture
def client() -> TestClient:
    validator = JwtValidator(ISSUER, AUDIENCE, FakeKeys())
    return TestClient(create_app(GraphStore(UNREACHABLE), validator))


def _post(
    client: TestClient,
    query: str,
    variables: dict[str, Any] | None = None,
    authorization: str | None = None,
) -> httpx.Response:
    headers = {"Authorization": authorization} if authorization else {}
    response: httpx.Response = client.post(
        "/graphql", json={"query": query, "variables": variables or {}}, headers=headers
    )
    return response


def _reader(
    client: TestClient, query: str, variables: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = _post(client, query, variables, f"Bearer {_token(['read_only_auditor'])}")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def test_graphql_requires_a_bearer_token(client: TestClient) -> None:
    response = _post(client, TYPENAME)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_other_authorization_schemes_are_refused(client: TestClient) -> None:
    assert _post(client, TYPENAME, authorization="Basic YTpi").status_code == 401


def test_tokens_signed_by_another_key_are_refused(client: TestClient) -> None:
    token = _token(["read_only_auditor"], OTHER_KEY)
    assert _post(client, TYPENAME, authorization=f"Bearer {token}").status_code == 401


def test_a_valid_token_without_realm_role_is_forbidden(client: TestClient) -> None:
    token = _token(["offline_access"])
    assert _post(client, TYPENAME, authorization=f"Bearer {token}").status_code == 403


@pytest.mark.parametrize("role", ROLES)
def test_every_realm_role_can_read(client: TestClient, role: str) -> None:
    response = _post(client, TYPENAME, authorization=f"Bearer {_token([role])}")
    assert response.status_code == 200
    assert response.json() == {"data": {"__typename": "Query"}}


def test_liveness_stays_open(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"service": "argos-inventory", "status": "alive"}


def test_the_deepest_query_of_the_contract_is_accepted() -> None:
    """node/neighbors/items/node is MAX_QUERY_DEPTH levels: the limiter must let it through."""
    result = build_schema().execute_sync(
        '{ node(key: "k") { neighbors { items { node { key } } } } }', context_value={}
    )
    assert "exceeds maximum operation depth" not in str(result.errors)


def test_operation_depth_is_limited() -> None:
    """The limiter exempts introspection, so it is exercised over a deeper nested schema."""
    schema = strawberry.Schema(
        query=DeepQuery, extensions=[lambda: QueryDepthLimiter(max_depth=MAX_QUERY_DEPTH)]
    )
    allowed = schema.execute_sync("{ level { next { next { next { name } } } } }")
    assert allowed.errors is None
    refused = schema.execute_sync("{ level { next { next { next { next { name } } } } } }")
    assert refused.errors is not None
    assert "exceeds maximum operation depth" in refused.errors[0].message


@pytest.mark.parametrize(
    ("query", "variables", "message"),
    [
        (
            "query($s: JSON!) { resolveSelector(selector: $s, first: 501) { hasNextPage } }",
            {"s": {"label": "Column"}},
            "first must be between 1 and 500",
        ),
        (
            "query($s: JSON!) { resolveSelector(selector: $s) { hasNextPage } }",
            {"s": {"label": "Column) DETACH DELETE n //"}},
            "unknown node label",
        ),
        (
            "query($s: JSON!) { resolveSelector(selector: $s) { hasNextPage } }",
            {"s": [1, 2]},
            "selector must be a JSON object",
        ),
        (
            '{ node(key: "k", after: "%%%") { props } }',
            None,
            "invalid cursor",
        ),
    ],
)
def test_arguments_are_checked_before_touching_the_graph(
    client: TestClient, query: str, variables: dict[str, Any] | None, message: str
) -> None:
    body = _reader(client, query, variables)
    assert message in body["errors"][0]["message"]
