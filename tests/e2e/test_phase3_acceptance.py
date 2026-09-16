"""Phase 3 acceptance test (Plan Director §8.2 "Fase 03").

A full scan of the simulated demonstration environment yields the hand-maintained ground truth:
systems, tables, classifications, flows and AI candidates. A second scan after provoked changes
reports exactly those changes, and a snapshot taken before them stays intact and servable through
the GraphQL API while the live graph moves.
"""

import asyncio
import time
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from fixtures.ground_truth import GroundTruth, load_ground_truth
from integration.conftest import ADMIN_DSN, MIGRATIONS_DIR
from integration.inventory_helpers import IngestingBus, RecordingBus, probe_runner, secret_store
from integration.sources import register_catalog_system
from psycopg import sql
from psycopg.types.json import Jsonb

from argos_auth import JwtValidator
from argos_common.journal_pg import PostgresJournal
from argos_common.migrations import apply_migrations
from argos_inventory.ai_discovery.detect import discover_ai
from argos_inventory.api.app import create_app
from argos_inventory.catalog.views import refresh_catalog
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.discovery.scanner import scan_system
from argos_inventory.flows.detect import detect_engine_links, detect_structural
from argos_inventory.graph.store import GraphStore
from argos_inventory.versioning.deltas import compute_deltas
from argos_inventory.versioning.snapshots import snapshot_nodes, take_snapshot, verify_snapshot

pytestmark = pytest.mark.integration

FAST_BUDGET = {"queries_per_minute": 600, "burst": 100}
ISSUER = "http://127.0.0.1:8180/realms/argos"
AUDIENCE = "argos-platform"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
# Idempotent: puts the PostgreSQL source back to the F03-00 seeds whatever state it is in.
RESTORE_POSTGRES = (
    "DROP TABLE IF EXISTS clinic.referrals",
    "CREATE TABLE IF NOT EXISTS clinic.readmission_risk ("
    " patient_id bigint PRIMARY KEY REFERENCES clinic.patients(id),"
    " risk_score numeric(4, 3) NOT NULL, predicted_at timestamptz NOT NULL)",
    "INSERT INTO clinic.readmission_risk SELECT g, ((g * 37) % 1000) / 1000.0,"
    " timestamptz '2026-01-01' + make_interval(hours => g) FROM generate_series(1, 5000) AS g"
    " ON CONFLICT DO NOTHING",
    "GRANT ALL ON clinic.readmission_risk TO clinic_admin",
    "GRANT SELECT ON clinic.readmission_risk TO argos_ro",
    "DELETE FROM clinic.appointments WHERE id > 20000",
    "ANALYZE clinic.readmission_risk",
    "ANALYZE clinic.appointments",
)
SNAPSHOT = (
    "query($id: String!, $after: String) { snapshot(id: $id, first: 200, after: $after) {"
    " nodeCount items { key name qualifiedName } endCursor hasNextPage } }"
)
_TABLES = (
    "MATCH (:System {id: $sid})-[:CONTAINS]->(:Schema)-[:CONTAINS]->(t:Table)"
    "-[:CONTAINS]->(c:Column) "
    "WHERE coalesce(t.missing, false) = false RETURN t.qualified_name, c.name"
)
_CLASSIFIED = (
    "MATCH (s:System)-[:CONTAINS*3]->(c:Column)-[r:CLASSIFIED_AS]->(k:Category) "
    "RETURN s.id, c.qualified_name, k.name, r.method"
)
_FLOWS = "MATCH (a:System)-[f:FLOWS_TO]->(b:System) RETURN a.id, b.id, f.method, f.confidence"
_AI = "MATCH (s:System)-[:USES_MODEL]->(a:AISystem) RETURN s.id, a.signals, a.status"


class FakeKeys:
    def get_signing_key_from_jwt(self, token: str) -> Any:
        return SimpleNamespace(key=KEY.public_key())


def _token() -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u-phase3",
        "iat": now,
        "exp": now + 600,
        "realm_access": {"roles": ["read_only_auditor"]},
    }
    return jwt.encode(claims, KEY, algorithm="RS256")


def _owner_sql(dsn: str, statements: tuple[str, ...]) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for statement in statements:
            conn.execute(statement)


@pytest.fixture
def truth() -> GroundTruth:
    return load_ground_truth()


@pytest.fixture
def phase3_db() -> Iterator[str]:
    name = f"argos_phase3_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        dsn = f"{ADMIN_DSN.rsplit('/', 1)[0]}/{name}"
        apply_migrations(dsn, MIGRATIONS_DIR)
        yield dsn
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
            conn.execute(drop.format(sql.Identifier(name)))


@pytest.fixture
def owner_dsn(truth: GroundTruth) -> Iterator[str]:
    [change] = truth.provoked_changes
    _owner_sql(change.owner_dsn, RESTORE_POSTGRES)
    try:
        yield change.owner_dsn
    finally:
        _owner_sql(change.owner_dsn, RESTORE_POSTGRES)


def _register(dsn: str, name: str) -> str:
    system_id = register_catalog_system(dsn, name)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE argos.systems SET connection = jsonb_set(connection, '{config,budget}', %s) "
            "WHERE id = %s",
            (Jsonb(FAST_BUDGET), system_id),
        )
    return system_id


def _scan(dsn: str, system_id: str) -> str:
    summary = asyncio.run(scan_system(dsn, secret_store(), IngestingBus(dsn), system_id))
    assert summary.status == "completed", (system_id, summary.error)
    return summary.run_id


def _analyse(store: GraphStore, dsn: str, ids: dict[str, str], truth: GroundTruth) -> None:
    runner = probe_runner(dsn)
    for name, spec in truth.systems.items():
        if spec["kind"] == "rdbms":
            classify_new_columns(store, runner, ids[name])
            detect_engine_links(store, dsn, runner, ids[name])
    detect_structural(store)
    discover_ai(store)
    refresh_catalog(dsn)


def _check_inventory(store: GraphStore, ids: dict[str, str], truth: GroundTruth) -> None:
    systems = store.query(
        "MATCH (s:System) WHERE s.last_scan_status = 'completed' RETURN s.id, s.kind",
        columns=("id", "kind"),
    )
    assert {r["id"]: r["kind"] for r in systems} == {
        ids[name]: spec["kind"] for name, spec in truth.systems.items()
    }

    for name, spec in truth.systems.items():
        if "tables" not in spec:
            continue
        found: dict[str, set[str]] = {}
        for row in store.query(_TABLES, {"sid": ids[name]}, ("table", "column")):
            found.setdefault(str(row["table"]), set()).add(str(row["column"]))
        assert found == {t: set(c) for t, c in truth.tables(name).items()}, name

    names = {system_id: name for name, system_id in ids.items()}
    classified = {
        (names[r["system"]], r["column"], r["category"], r["method"])
        for r in store.query(_CLASSIFIED, columns=("system", "column", "category", "method"))
    }
    assert classified == {(c.system, c.column, c.category, c.method) for c in truth.classifications}
    assert not {(s, c) for s, c, _, _ in classified} & set(truth.unclassified)

    flows = store.query(_FLOWS, columns=("a", "b", "method", "confidence"))
    for flow in truth.flows:
        pair = (ids[flow.source], ids[flow.target])
        matches = [
            f
            for f in flows
            if f["method"] == flow.method
            and ((f["a"], f["b"]) == pair or (flow.undirected and (f["b"], f["a"]) == pair))
        ]
        assert matches, flow
        assert all(
            flow.min_confidence <= float(f["confidence"]) <= flow.max_confidence for f in matches
        )

    candidates = store.query(_AI, columns=("system", "signals", "status"))
    for expected in truth.ai_candidates:
        assert any(
            c["system"] == ids[expected.system]
            and c["status"] == "pending"
            and any(
                s.startswith(f"{expected.signal_kind}|") and expected.detail_contains in s
                for s in c["signals"]
            )
            for c in candidates
        ), expected


def _served_snapshot(client: TestClient, snapshot_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    after = None
    while True:
        response = client.post(
            "/graphql",
            json={"query": SNAPSHOT, "variables": {"id": snapshot_id, "after": after}},
            headers={"Authorization": f"Bearer {_token()}"},
        )
        page = response.json()["data"]["snapshot"]
        items.extend(page["items"])
        if not page["hasNextPage"]:
            return items
        after = page["endCursor"]


def test_phase3_inventory_matches_ground_truth_and_diffs_exactly(
    phase3_db: str, owner_dsn: str, truth: GroundTruth
) -> None:
    dsn, store = phase3_db, GraphStore(phase3_db)
    ids = {name: _register(dsn, name) for name in truth.systems}

    # 1) Full scan of the demonstration environment -> the hand-maintained ground truth.
    for system_id in ids.values():
        _scan(dsn, system_id)
    _analyse(store, dsn, ids, truth)
    _check_inventory(store, ids, truth)

    # 2) Snapshot taken before the changes.
    snapshot = take_snapshot(store, dsn, "phase-3-acceptance")
    frozen = snapshot_nodes(dsn, snapshot.id)
    frozen_names = {n["qualified_name"] for n in frozen}
    assert "clinic.readmission_risk" in frozen_names
    assert "clinic.referrals" not in frozen_names

    # 3) Provoked changes and a second scan: the diff is exactly the expected one.
    [change] = truth.provoked_changes
    _owner_sql(owner_dsn, change.sql)
    postgres = ids[change.system]
    run_id = _scan(dsn, postgres)
    report = compute_deltas(store, dsn, RecordingBus(), postgres, run_id)
    found_deltas = {
        (change.system, d.kind, d.label, d.detail["qualified_name"]) for d in report.deltas
    }
    assert found_deltas == {
        (d.system, d.kind, d.label, d.qualified_name) for d in truth.expected_deltas
    }
    classify_new_columns(store, probe_runner(dsn), postgres)  # the live graph keeps moving

    [live] = store.query(
        "MATCH (t:Table {qualified_name: 'clinic.readmission_risk'}) RETURN t.missing",
        columns=("missing",),
    )
    assert live["missing"] is True

    # 4) The snapshot is untouched and servable through the API while the live graph moved.
    assert verify_snapshot(dsn, snapshot.id)
    assert snapshot_nodes(dsn, snapshot.id) == frozen
    client = TestClient(create_app(store, JwtValidator(ISSUER, AUDIENCE, FakeKeys())))
    served = _served_snapshot(client, snapshot.id)
    assert [(i["key"], i["qualifiedName"]) for i in served] == [
        (n["node_key"], n["qualified_name"]) for n in frozen
    ]

    # 5) Every change and decision left an intact journal.
    assert PostgresJournal(dsn).verify().intact
