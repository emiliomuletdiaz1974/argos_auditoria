"""ARG-071 y ARG-074 · systems and inventory over the v1: coverage, node, review queue and graph.

What the DPO sees in the console and what an integration reads are the same thing, so these tests
walk the API, not the libraries: the queue resolves into the graph, into the journal and into the
material the calibration learns from, and the graph keeps the permission matrix in front of it.
"""

import asyncio
from collections.abc import Sequence
from typing import cast

import psycopg
import pytest
from argos_ai.classify.store import load_decisions, record_proposals
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_auth import Identity, JwtValidator
from argos_inventory.catalog.views import refresh_catalog
from argos_inventory.classify.assisted import ColumnContext, Proposal, classify_grey_zone
from argos_inventory.graph.model import column_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.ingest.handlers import Ingestor

from .inventory_helpers import RecordingBus
from .sources import register_catalog_system

pytestmark = pytest.mark.integration

AT = "2026-09-20T10:00:00+00:00"
BEARER = {"Authorization": "Bearer a-token"}
COLUMNS = ["campo07", "obs_txt", "dni_number"]
ANSWERS = {"campo07": ("personal_data", 0.9), "obs_txt": ("special_category.health", 0.7)}
GRAPH_QUERY = {"query": '{ node(key: "whatever") { node { key } } }'}


class RoleValidator:
    def __init__(self, roles: frozenset[str]) -> None:
        self._roles = roles

    def validate(self, token: str) -> Identity:
        return Identity(sub="someone", name="Someone", roles=self._roles)


class FakeModel:
    def propose(self, columns: Sequence[ColumnContext]) -> list[Proposal]:
        return [
            Proposal(c.key, *ANSWERS[c.name], reason="synthetic")
            for c in columns
            if c.name in ANSWERS
        ]


def _client(dsn: str, *roles: str) -> TestClient:
    validator = cast(JwtValidator, RoleValidator(frozenset(roles)))
    return TestClient(create_app(validator, dsn=dsn))


@pytest.fixture
def inventory(migrated_db: str) -> tuple[str, str]:
    """A system with three columns, one of them waiting for a human decision."""
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    table = {
        "system_id": system_id,
        "run_id": "run-api",
        "source_connector": "argos_sql.postgres:PostgresConnector",
        "probe_id": "probe-api",
        "journal_seq": 1,
        "observed_at": AT,
        "schema": "legacy",
        "table": "records",
        "est_rows": 10,
        "bytes": 8192,
        "comment": None,
        "columns": [{"name": c, "type": "text", "nullable": True} for c in COLUMNS],
    }
    asyncio.run(
        Ingestor(store, migrated_db, RecordingBus()).handle(
            table, {"type": "eu.argos.discovery.table_found.v1"}
        )
    )
    classify_grey_zone(store, migrated_db, FakeModel(), system_id)
    refresh_catalog(migrated_db)
    node_key = column_key(system_id, "legacy", "records", "obs_txt")
    # The proposal as the gateway records it: without it the decision has nothing to calibrate.
    record_proposals(
        migrated_db,
        [
            {
                "node_key": node_key,
                "category": "special_category.health",
                "declared": 0.7,
                "calibrated": 0.7,
                "prompt_sha256": "0" * 64,
            }
        ],
    )
    return system_id, node_key


def test_the_systems_are_listed_page_by_page(inventory: tuple[str, str], migrated_db: str) -> None:
    client = _client(migrated_db, "read_only_auditor")
    first = client.get(f"{API_PREFIX}/systems", params={"limit": 1}, headers=BEARER)
    assert first.status_code == 200
    page = first.json()
    assert len(page["items"]) == 1
    assert {"id", "name", "kind", "environment"} <= set(page["items"][0])

    if page["next"]:
        second = client.get(
            f"{API_PREFIX}/systems", params={"limit": 1, "cursor": page["next"]}, headers=BEARER
        )
        assert second.status_code == 200
        assert second.json()["items"][0]["id"] != page["items"][0]["id"]


def test_a_cursor_that_is_not_ours_is_refused(inventory: tuple[str, str], migrated_db: str) -> None:
    answer = _client(migrated_db, "read_only_auditor").get(
        f"{API_PREFIX}/systems", params={"cursor": "made-up"}, headers=BEARER
    )
    assert answer.status_code == 400
    assert answer.headers["content-type"].startswith("application/problem+json")


def test_the_coverage_tells_what_is_known_of_each_system(
    inventory: tuple[str, str], migrated_db: str
) -> None:
    answer = _client(migrated_db, "dpo_reviewer").get(
        f"{API_PREFIX}/inventory/coverage", headers=BEARER
    )
    assert answer.status_code == 200
    body = answer.json()
    assert body["systems"], "the seeded system has to show up"
    assert "pending_review" in body["systems"][0]
    assert body["pending_review"] >= 1


def test_a_node_comes_with_its_neighbourhood(inventory: tuple[str, str], migrated_db: str) -> None:
    _, node_key = inventory
    client = _client(migrated_db, "read_only_auditor")
    answer = client.get(f"{API_PREFIX}/inventory/nodes/{node_key}", headers=BEARER)
    assert answer.status_code == 200
    body = answer.json()
    assert body["node"]["key"] == node_key
    assert body["node"]["label"] == "Column"
    assert body["neighbours"], "a column hangs at least from its table"

    missing = client.get(f"{API_PREFIX}/inventory/nodes/nothing-like-this", headers=BEARER)
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")


def test_the_queue_shows_what_waits_for_a_person(
    inventory: tuple[str, str], migrated_db: str
) -> None:
    _, node_key = inventory
    answer = _client(migrated_db, "dpo_reviewer").get(
        f"{API_PREFIX}/inventory/review-queue", headers=BEARER
    )
    assert answer.status_code == 200
    keys = [item["node_key"] for item in answer.json()["items"]]
    assert node_key in keys
    waiting = next(item for item in answer.json()["items"] if item["node_key"] == node_key)
    assert waiting["proposed_category"] == "special_category.health"
    assert waiting["status"] == "pending"


def test_accepting_a_column_writes_the_graph_the_journal_and_the_calibration(
    inventory: tuple[str, str], migrated_db: str
) -> None:
    _, node_key = inventory
    client = _client(migrated_db, "dpo_reviewer")
    answer = client.post(
        f"{API_PREFIX}/inventory/review-queue/{node_key}",
        json={"decision": "accept"},
        headers=BEARER,
    )
    assert answer.status_code == 200
    assert answer.json()["status"] == "accepted"

    edges = GraphStore(migrated_db).query(
        "MATCH (c:Column {key: $key})-[r:CLASSIFIED_AS]->(k:Category) "
        "RETURN k.name, r.method, r.reviewer",
        {"key": node_key},
        ("category", "method", "reviewer"),
    )
    assert any(e["method"] == "human" for e in edges), edges

    with psycopg.connect(migrated_db) as conn:
        entry = conn.execute(
            "SELECT actor, action FROM argos.audit_journal WHERE action = 'inventory.review'"
            " ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    assert entry is not None and str(entry[1]) == "inventory.review"

    assert any(d.category == "special_category.health" for d in load_decisions(migrated_db))


def test_a_column_is_decided_once(inventory: tuple[str, str], migrated_db: str) -> None:
    _, node_key = inventory
    client = _client(migrated_db, "dpo_reviewer")
    path = f"{API_PREFIX}/inventory/review-queue/{node_key}"
    assert client.post(path, json={"decision": "reject"}, headers=BEARER).status_code == 200
    again = client.post(path, json={"decision": "accept"}, headers=BEARER)
    assert again.status_code == 409
    assert again.headers["content-type"].startswith("application/problem+json")


def test_an_unknown_column_cannot_be_decided(inventory: tuple[str, str], migrated_db: str) -> None:
    answer = _client(migrated_db, "dpo_reviewer").post(
        f"{API_PREFIX}/inventory/review-queue/nothing-like-this",
        json={"decision": "accept"},
        headers=BEARER,
    )
    assert answer.status_code == 404


def test_the_graph_is_behind_the_same_matrix(inventory: tuple[str, str], migrated_db: str) -> None:
    graph = f"{API_PREFIX}/inventory/graph"
    reader = _client(migrated_db, "read_only_auditor")
    assert reader.post(graph, json=GRAPH_QUERY, headers=BEARER).status_code == 200

    anonymous = _client(migrated_db, "read_only_auditor")
    assert anonymous.post(graph, json=GRAPH_QUERY).status_code == 401

    stranger = _client(migrated_db)  # a valid token with no role of the realm
    assert stranger.post(graph, json=GRAPH_QUERY, headers=BEARER).status_code == 403


def test_reading_the_inventory_leaves_no_journal_entry(
    inventory: tuple[str, str], migrated_db: str
) -> None:
    with psycopg.connect(migrated_db) as conn:
        before = conn.execute("SELECT count(*) FROM argos.audit_journal").fetchone()
    _client(migrated_db, "read_only_auditor").get(f"{API_PREFIX}/systems", headers=BEARER)
    with psycopg.connect(migrated_db) as conn:
        after = conn.execute("SELECT count(*) FROM argos.audit_journal").fetchone()
    assert before == after


def test_correcting_a_column_teaches_the_calibration_and_writes_the_right_category(
    inventory: tuple[str, str], migrated_db: str
) -> None:
    _, node_key = inventory
    answer = _client(migrated_db, "dpo_reviewer").post(
        f"{API_PREFIX}/inventory/review-queue/{node_key}",
        json={"decision": "correct", "category": "special_category.other"},
        headers=BEARER,
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["status"] == "rejected", "the model was wrong: that is the label"
    assert answer.json()["corrected_to"] == "special_category.other"

    edges = GraphStore(migrated_db).query(
        "MATCH (c:Column {key: $key})-[r:CLASSIFIED_AS]->(k:Category) RETURN k.name, r.method",
        {"key": node_key},
        ("category", "method"),
    )
    assert {"category": "special_category.other", "method": "human"} in edges
    decided = [d for d in load_decisions(migrated_db) if d.category == "special_category.health"]
    assert decided and not decided[-1].right


def test_a_correction_needs_a_known_category(inventory: tuple[str, str], migrated_db: str) -> None:
    _, node_key = inventory
    client = _client(migrated_db, "dpo_reviewer")
    path = f"{API_PREFIX}/inventory/review-queue/{node_key}"
    assert client.post(path, json={"decision": "correct"}, headers=BEARER).status_code == 422
    unknown = client.post(path, json={"decision": "correct", "category": "made_up"}, headers=BEARER)
    assert unknown.status_code == 422


def test_a_node_carries_its_timeline_of_deltas(
    inventory: tuple[str, str], migrated_db: str
) -> None:
    system_id, node_key = inventory
    with psycopg.connect(migrated_db) as conn:
        run = conn.execute(
            "INSERT INTO argos.scan_runs (id, system_id, status, started_at, finished_at)"
            " VALUES (gen_random_uuid(), %s, 'completed', now(), now()) RETURNING id",
            (system_id,),
        ).fetchone()
        assert run is not None
        conn.execute(
            "INSERT INTO argos.inventory_deltas (run_id, kind, node_label, node_key)"
            " VALUES (%s, 'appeared', 'Column', %s)",
            (run[0], node_key),
        )
    body = (
        _client(migrated_db, "read_only_auditor")
        .get(f"{API_PREFIX}/inventory/nodes/{node_key}", headers=BEARER)
        .json()
    )
    assert [delta["kind"] for delta in body["deltas"]] == ["appeared"]
    assert body["deltas"][0]["at"]
