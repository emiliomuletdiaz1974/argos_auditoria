"""ARG-025 · assisted classification: thresholds, review queue and the DPO decision."""

import asyncio
from collections.abc import Sequence
from typing import Any

import psycopg
import pytest

from argos_inventory.classify.assisted import (
    ColumnContext,
    NullModel,
    Proposal,
    classify_grey_zone,
    decide_review,
)
from argos_inventory.graph.model import column_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.ingest.handlers import Ingestor

from .inventory_helpers import RecordingBus
from .sources import register_catalog_system

pytestmark = pytest.mark.integration

AT = "2026-09-15T10:00:00+00:00"
REVIEWER = "user:0192b000-0000-7000-8000-00000000d0c0"
COLUMNS = ["campo07", "cod_x", "dni_number", "obs_txt"]
TABLE_FOUND = {"type": "eu.argos.discovery.table_found.v1"}


class FakeModel:
    def __init__(self, answers: dict[str, tuple[str, float]]) -> None:
        self.answers = answers
        self.batches: list[list[ColumnContext]] = []

    def propose(self, columns: Sequence[ColumnContext]) -> list[Proposal]:
        self.batches.append(list(columns))
        proposals = [
            Proposal(c.key, *self.answers[c.name], reason="synthetic")
            for c in columns
            if c.name in self.answers
        ]
        return [*proposals, Proposal("not-in-batch", "personal_data", 0.99)]


def _graph(dsn: str) -> tuple[str, GraphStore]:
    system_id = register_catalog_system(dsn, "dev-source-postgres")
    store = GraphStore(dsn)
    table = {
        "system_id": system_id,
        "run_id": "run-1",
        "source_connector": "argos_sql.postgres:PostgresConnector",
        "probe_id": "probe-1",
        "journal_seq": 1,
        "observed_at": AT,
        "schema": "legacy",
        "table": "records",
        "est_rows": 10,
        "bytes": 8192,
        "comment": None,
        "columns": [{"name": c, "type": "text", "nullable": True} for c in COLUMNS],
    }
    asyncio.run(Ingestor(store, dsn, RecordingBus()).handle(table, TABLE_FOUND))
    store.execute(
        "MATCH (c:Column {key: $key}), (k:Category {name: 'official_identifier'}) "
        "MERGE (c)-[r:CLASSIFIED_AS]->(k) SET r.method = 'dict' SET r.confidence = 0.6",
        {"key": column_key(system_id, "legacy", "records", "dni_number")},
    )
    return system_id, store


def _key(system_id: str, name: str) -> str:
    return column_key(system_id, "legacy", "records", name)


def _edge(store: GraphStore, key: str) -> list[dict[str, Any]]:
    return store.query(
        "MATCH (c:Column {key: $key})-[r:CLASSIFIED_AS]->(k:Category) "
        "RETURN k.name, r.method, r.confidence, r.prompt_hash, r.reviewer",
        {"key": key},
        ("category", "method", "confidence", "prompt_hash", "reviewer"),
    )


def _queue(dsn: str, key: str) -> tuple[Any, ...] | None:
    with psycopg.connect(dsn) as conn:
        return conn.execute(
            "SELECT proposed_category, confidence::float, status, decided_by "
            "FROM argos.review_queue WHERE node_key = %s",
            (key,),
        ).fetchone()


ANSWERS = {
    "campo07": ("personal_data", 0.9),
    "obs_txt": ("special_category.health", 0.7),
    "cod_x": ("no_personal_data", 0.2),
}


def test_model_proposals_are_triaged_by_threshold(migrated_db: str) -> None:
    system_id, store = _graph(migrated_db)
    model = FakeModel(ANSWERS)
    summary = classify_grey_zone(store, migrated_db, model, system_id)
    counts = (summary.sent, summary.accepted, summary.queued, summary.ignored, summary.invalid)
    assert counts == (3, 1, 1, 1, 1)

    [sent] = model.batches
    # dni_number already has a deterministic classification
    assert sorted(c.name for c in sent) == ["campo07", "cod_x", "obs_txt"]
    assert all("dni_number" in c.siblings for c in sent)

    [ai] = _edge(store, _key(system_id, "campo07"))
    assert (ai["category"], ai["method"], ai["confidence"]) == ("personal_data", "ai", 0.9)
    assert len(ai["prompt_hash"]) == 16
    assert _edge(store, _key(system_id, "obs_txt")) == []
    assert _edge(store, _key(system_id, "cod_x")) == []
    pending = ("special_category.health", 0.7, "pending", None)
    assert _queue(migrated_db, _key(system_id, "obs_txt")) == pending
    assert _queue(migrated_db, _key(system_id, "cod_x")) is None


def test_the_null_model_leaves_the_grey_zone_visible(migrated_db: str) -> None:
    system_id, store = _graph(migrated_db)
    summary = classify_grey_zone(store, migrated_db, NullModel(), system_id)
    assert (summary.sent, summary.accepted, summary.queued) == (3, 0, 0)
    assert _edge(store, _key(system_id, "campo07")) == []


def test_batches_respect_the_batch_size(migrated_db: str) -> None:
    system_id, store = _graph(migrated_db)
    model = FakeModel(ANSWERS)
    classify_grey_zone(store, migrated_db, model, system_id, batch_size=2)
    assert [len(batch) for batch in model.batches] == [2, 1]


def test_accepting_a_review_writes_a_human_edge_and_a_journal_entry(migrated_db: str) -> None:
    system_id, store = _graph(migrated_db)
    classify_grey_zone(store, migrated_db, FakeModel(ANSWERS), system_id)
    key = _key(system_id, "obs_txt")
    assert decide_review(store, migrated_db, key, True, REVIEWER) == "accepted"
    [human] = _edge(store, key)
    assert (human["category"], human["method"], human["confidence"], human["reviewer"]) == (
        "special_category.health",
        "human",
        1.0,
        REVIEWER,
    )
    assert _queue(migrated_db, key) == ("special_category.health", 0.7, "accepted", REVIEWER)
    with psycopg.connect(migrated_db) as conn:
        entries = conn.execute(
            "SELECT actor, payload->>'node_key', payload->>'status' FROM argos.audit_journal "
            "WHERE action = 'inventory.review'"
        ).fetchall()
    assert entries == [(REVIEWER, key, "accepted")]
    with pytest.raises(ValueError, match="already decided"):
        decide_review(store, migrated_db, key, False, REVIEWER)


def test_rejecting_a_review_writes_no_edge_and_blocks_new_proposals(migrated_db: str) -> None:
    system_id, store = _graph(migrated_db)
    classify_grey_zone(store, migrated_db, FakeModel(ANSWERS), system_id)
    key = _key(system_id, "obs_txt")
    assert decide_review(store, migrated_db, key, False, REVIEWER) == "rejected"
    assert _edge(store, key) == []
    second = FakeModel({"obs_txt": ("contact_data", 0.6)})
    classify_grey_zone(store, migrated_db, second, system_id)
    assert _queue(migrated_db, key) == ("special_category.health", 0.7, "rejected", REVIEWER)


def test_a_pending_review_is_updated_by_a_new_proposal(migrated_db: str) -> None:
    system_id, store = _graph(migrated_db)
    classify_grey_zone(store, migrated_db, FakeModel(ANSWERS), system_id)
    second = FakeModel({"obs_txt": ("contact_data", 0.6)})
    classify_grey_zone(store, migrated_db, second, system_id)
    updated = ("contact_data", 0.6, "pending", None)
    assert _queue(migrated_db, _key(system_id, "obs_txt")) == updated


def test_unknown_reviews_are_reported(migrated_db: str) -> None:
    _, store = _graph(migrated_db)
    with pytest.raises(LookupError):
        decide_review(store, migrated_db, "missing-key", True, REVIEWER)
