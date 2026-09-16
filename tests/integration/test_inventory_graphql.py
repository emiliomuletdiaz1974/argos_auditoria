"""ARG-029 · the inventory GraphQL API over a scanned, classified and snapshotted graph."""

import time
import uuid
from types import SimpleNamespace
from typing import Any

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from fixtures.ground_truth import load_ground_truth

from argos_auth import JwtValidator
from argos_inventory.api.app import create_app
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.model import column_key, system_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.versioning.snapshots import snapshot_nodes, take_snapshot

from .inventory_helpers import probe_runner, scan_and_ingest

pytestmark = pytest.mark.integration

ISSUER = "http://127.0.0.1:8180/realms/argos"
AUDIENCE = "argos-platform"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SELECT_NODES = (
    "query($s: JSON!, $first: Int!, $after: String) {"
    " resolveSelector(selector: $s, first: $first, after: $after) {"
    " items { key label name qualifiedName systemId } endCursor hasNextPage } }"
)
NODE = (
    "query($key: String!, $first: Int!, $after: String) {"
    " node(key: $key, first: $first, after: $after) { node { label name } props"
    " neighbors { items { edge direction node { label name } } endCursor hasNextPage } } }"
)
SNAPSHOT = (
    "query($id: String!, $first: Int!, $after: String) {"
    " snapshot(id: $id, first: $first, after: $after) { label nodeCount contentHash"
    " items { key name categories } endCursor hasNextPage } }"
)


class FakeKeys:
    def get_signing_key_from_jwt(self, token: str) -> Any:
        return SimpleNamespace(key=KEY.public_key())


def _token() -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u-inventory",
        "iat": now,
        "exp": now + 300,
        "realm_access": {"roles": ["read_only_auditor"]},
    }
    return jwt.encode(claims, KEY, algorithm="RS256")


def _client(dsn: str) -> TestClient:
    return TestClient(create_app(GraphStore(dsn), JwtValidator(ISSUER, AUDIENCE, FakeKeys())))


def _gql(client: TestClient, query: str, **variables: Any) -> dict[str, Any]:
    response = client.post(
        "/graphql",
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _all_pages(client: TestClient, selector: dict[str, Any], first: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    after = None
    while True:
        body = _gql(client, SELECT_NODES, s=selector, first=first, after=after)
        page = body["data"]["resolveSelector"]
        assert len(page["items"]) <= first
        items.extend(page["items"])
        if not page["hasNextPage"]:
            return items
        after = page["endCursor"]


@pytest.fixture
def classified(migrated_db: str) -> tuple[str, str]:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    classify_new_columns(GraphStore(migrated_db), probe_runner(migrated_db), system_id)
    return migrated_db, system_id


def test_selector_returns_the_ground_truth_identifiers(classified: tuple[str, str]) -> None:
    dsn, system_id = classified
    selector = {"label": "Column", "category": "official_identifier", "missing": False}
    items = _all_pages(_client(dsn), selector, 500)
    found = {i["qualifiedName"] for i in items if i["systemId"] == system_id}
    expected = {
        c.column
        for c in load_ground_truth().classifications
        if c.system == "dev-source-postgres" and c.category == "official_identifier"
    }
    assert expected <= found
    assert {i["label"] for i in items} == {"Column"}


def test_system_kind_and_name_prefix_filter_tables(classified: tuple[str, str]) -> None:
    dsn, _ = classified
    client = _client(dsn)
    selector = {"label": "Table", "system_kind": "rdbms", "name_like": "patient"}
    names = {i["name"] for i in _all_pages(client, selector, 50)}
    assert {"patients", "patient_documents"} <= names
    assert all(name.startswith("patient") for name in names)
    assert _all_pages(client, {"label": "Table", "system_kind": "files"}, 50) == []


def test_pagination_visits_every_column_exactly_once(classified: tuple[str, str]) -> None:
    dsn, _ = classified
    keys = [i["key"] for i in _all_pages(_client(dsn), {"label": "Column"}, 7)]
    [row] = GraphStore(dsn).query("MATCH (c:Column) RETURN count(c)", columns=("n",))
    assert len(keys) == len(set(keys)) == row["n"]
    assert keys == sorted(keys)


def test_node_returns_its_neighbourhood_page_by_page(classified: tuple[str, str]) -> None:
    dsn, system_id = classified
    client = _client(dsn)
    detail = _gql(client, NODE, key=system_key(system_id), first=50)["data"]["node"]
    assert detail["node"]["label"] == "System"
    assert detail["props"]["id"] == system_id
    schema = {"edge": "CONTAINS", "direction": "out", "node": {"label": "Schema", "name": "clinic"}}
    assert schema in detail["neighbors"]["items"]

    seen: list[tuple[str, str, str]] = []
    after = None
    column = column_key(system_id, "clinic", "patients", "national_id")
    while True:
        page = _gql(client, NODE, key=column, first=1, after=after)["data"]["node"]["neighbors"]
        assert len(page["items"]) <= 1
        seen.extend((n["edge"], n["direction"], n["node"]["label"]) for n in page["items"])
        if not page["hasNextPage"]:
            break
        after = page["endCursor"]
    assert ("CONTAINS", "in", "Table") in seen
    assert ("CLASSIFIED_AS", "out", "Category") in seen
    assert len(seen) == len(set(seen))
    assert _gql(client, NODE, key="0" * 40, first=10)["data"]["node"] is None


def test_snapshot_is_served_unchanged_while_the_live_graph_moves(
    classified: tuple[str, str],
) -> None:
    dsn, _ = classified
    store = GraphStore(dsn)
    ref = take_snapshot(store, dsn, "api-test")
    store.execute("MATCH (t:Table {name: 'patients'}) SET t.name = 'patients_renamed'")
    client = _client(dsn)

    items: list[dict[str, Any]] = []
    after = None
    while True:
        page = _gql(client, SNAPSHOT, id=ref.id, first=50, after=after)["data"]["snapshot"]
        assert (page["label"], page["nodeCount"], page["contentHash"]) == (
            "api-test",
            ref.node_count,
            ref.content_hash,
        )
        items.extend(page["items"])
        if not page["hasNextPage"]:
            break
        after = page["endCursor"]
    stored = snapshot_nodes(dsn, ref.id)
    assert [(i["key"], i["name"], i["categories"]) for i in items] == [
        (r["node_key"], r["name"], r["categories"]) for r in stored
    ]
    served = {i["name"] for i in items}
    assert "patients" in served and "patients_renamed" not in served
    live = {i["name"] for i in _all_pages(client, {"label": "Table", "name_like": "patients"}, 50)}
    assert "patients_renamed" in live
    assert _gql(client, SNAPSHOT, id=str(uuid.uuid4()), first=10)["data"]["snapshot"] is None
    missing = _gql(client, SNAPSHOT, id="nope", first=10)
    assert "invalid snapshot id" in missing["errors"][0]["message"]


@pytest.mark.parametrize(
    ("selector", "rejected"),
    [
        ({"label": "Column) DETACH DELETE n //"}, True),
        ({"label": "Table", "name_like": "x' }) DETACH DELETE n //"}, False),
        (
            {"label": "Table", "category": "$$) AS (v agtype); DROP TABLE argos.scan_runs; --"},
            False,
        ),
    ],
)
def test_injection_attempts_leave_the_graph_untouched(
    classified: tuple[str, str], selector: dict[str, Any], rejected: bool
) -> None:
    dsn, _ = classified
    store = GraphStore(dsn)
    count = "MATCH (n) RETURN count(n)"
    before = store.query(count, columns=("n",))
    body = _gql(_client(dsn), SELECT_NODES, s=selector, first=10)
    assert store.query(count, columns=("n",)) == before
    if rejected:
        assert "unknown node label" in body["errors"][0]["message"]
    else:
        assert body["data"]["resolveSelector"]["items"] == []
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT to_regclass('argos.scan_runs')").fetchone() != (None,)
