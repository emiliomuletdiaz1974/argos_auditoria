"""ARG-028 · AI discovery over the simulated sources, accumulation and DPO confirmation."""

import asyncio

import psycopg
import pytest
from fixtures.ground_truth import load_ground_truth

from argos_inventory.ai_discovery.detect import (
    Signal,
    confirm_ai_system,
    discover_ai,
    provisional_register,
    record_signal,
)
from argos_inventory.graph.model import ai_system_key, system_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.ingest.handlers import Ingestor

from .inventory_helpers import RecordingBus, scan_and_ingest
from .sources import register_catalog_system

pytestmark = pytest.mark.integration

AT = "2026-09-15T10:00:00+00:00"
DPO = "user:0192b000-0000-7000-8000-00000000d0c0"
CANDIDATES = (
    "MATCH (s:System)-[:USES_MODEL]->(a:AISystem) "
    "RETURN s.id, a.key, a.name, a.signals, a.confidence, a.status"
)
CANDIDATE_COLUMNS = ("system", "key", "name", "signals", "confidence", "status")
AUDIT = (
    "SELECT actor, payload->>'key', payload->>'risk_class' FROM argos.audit_journal "
    "WHERE action = 'inventory.ai_confirm'"
)


def _candidates(store: GraphStore) -> list[dict[str, object]]:
    return store.query(CANDIDATES, columns=CANDIDATE_COLUMNS)


def test_candidates_match_the_ground_truth(migrated_db: str) -> None:
    ids = {
        name: scan_and_ingest(migrated_db, name)
        for name in ("dev-source-postgres", "dev-files-local", "dev-files-smb")
    }
    store = GraphStore(migrated_db)
    summary = discover_ai(store)
    assert summary.columns >= 1 and summary.files >= 2
    found = _candidates(store)
    for expected in load_ground_truth().ai_candidates:
        matches = [
            c
            for c in found
            if c["system"] == ids[expected.system]
            and any(
                s.startswith(f"{expected.signal_kind}|") and expected.detail_contains in s
                for s in c["signals"]  # type: ignore[union-attr]
            )
        ]
        assert matches, expected
        assert all(m["status"] == "pending" for m in matches)
    readmission = next(c for c in found if c["name"] == "table:readmission_risk")
    assert readmission["confidence"] == 0.3


def test_signals_accumulate_without_duplicates(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    store.execute(
        "MERGE (s:System {key: $key}) SET s.id = $id",
        {"key": system_key(system_id), "id": system_id},
    )
    score = Signal("score_column", 0.3, "readmission_risk")
    model = Signal("model_file", 0.4, "onnx")
    assert record_signal(store, system_id, "table:readmission_risk", score, AT) == 0.3
    assert record_signal(store, system_id, "table:readmission_risk", score, AT) == 0.3
    assert record_signal(store, system_id, "table:readmission_risk", model, AT) == 0.58
    [candidate] = _candidates(store)
    assert sorted(candidate["signals"]) == [  # type: ignore[arg-type]
        "model_file|0.4|onnx",
        "score_column|0.3|readmission_risk",
    ]


def test_routes_feed_the_provisional_register(migrated_db: str) -> None:
    system_id = register_catalog_system(migrated_db, "dev-api-keycloak")
    store = GraphStore(migrated_db)
    routes = {
        "system_id": system_id,
        "run_id": "run-1",
        "source_connector": "argos_rest.connector:RestConnector",
        "probe_id": "p",
        "journal_seq": 1,
        "observed_at": AT,
        "routes": [
            {"path": "/v1/chat/completions", "status": 405, "content_type": None},
            {"path": "/realms/{realm}", "status": 405, "content_type": None},
        ],
    }
    asyncio.run(
        Ingestor(store, migrated_db, RecordingBus()).handle(
            routes, {"type": "eu.argos.discovery.api_routes_found.v1"}
        )
    )
    assert discover_ai(store).routes == 1
    register = provisional_register(store)
    assert [(r["name"], r["confidence"], r["status"]) for r in register] == [
        ("api:/v1/chat/completions", 0.5, "pending")
    ]


def test_the_dpo_confirms_with_ai_act_fields_and_it_survives_rediscovery(migrated_db: str) -> None:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    discover_ai(store)
    key = ai_system_key(system_id, "table:readmission_risk")
    confirm_ai_system(store, migrated_db, key, DPO, "Readmission risk scoring (synthetic)", "high")
    discover_ai(store)
    [row] = store.query(
        "MATCH (a:AISystem {key: $key}) RETURN a.status, a.purpose, a.risk_class, a.confirmed_by",
        {"key": key},
        ("status", "purpose", "risk", "by"),
    )
    assert row == {
        "status": "confirmed",
        "purpose": "Readmission risk scoring (synthetic)",
        "risk": "high",
        "by": DPO,
    }
    assert any(r["key"] == key for r in provisional_register(store))
    with psycopg.connect(migrated_db) as conn:
        entries = conn.execute(AUDIT).fetchall()
    assert entries == [(DPO, key, "high")]


@pytest.mark.parametrize(
    ("reviewer", "risk_class", "message"),
    [("system:inventory", "high", "user:"), (DPO, "very-high", "risk class")],
)
def test_invalid_confirmations_are_refused(
    migrated_db: str, reviewer: str, risk_class: str, message: str
) -> None:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    discover_ai(store)
    key = ai_system_key(system_id, "table:readmission_risk")
    with pytest.raises(ValueError, match=message):
        confirm_ai_system(store, migrated_db, key, reviewer, "x", risk_class)
