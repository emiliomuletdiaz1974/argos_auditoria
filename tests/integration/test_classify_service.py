"""ARG-055 · the calibration learns from the DPO's decisions in the real review queue (F06-08)."""

import json
from datetime import UTC, datetime

import psycopg
import pytest
from argos_ai.backends.fake import FakeBackend
from argos_ai.classify.calibration import UNTRUSTED_CEILING
from argos_ai.classify.service import SemanticClassifier
from argos_ai.classify.store import drift, record_proposals, refit, stored_calibrator
from argos_ai.quotas import postgres_gateway

from argos_inventory.classify.assisted import ColumnContext

from .sources import register_catalog_system

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 30, tzinfo=UTC)


def _queue(dsn: str, rows: list[tuple[str, str, float, str]]) -> None:
    """What ARG-025 left in the review queue after the DPO decided: key, category, conf, status."""
    system_id = register_catalog_system(dsn, "dev-source-postgres")
    with psycopg.connect(dsn) as conn:
        for key, category, confidence, status in rows:
            decided = status != "pending"
            conn.execute(
                "INSERT INTO argos.review_queue (node_key, system_id, qualified_name, "
                "proposed_category, confidence, reason, prompt_hash, proposed_at, status, "
                "decided_at, decided_by) "
                "VALUES (%s, %s, %s, %s, %s, '', 'abcdef0123456789', %s, %s, %s, %s)",
                (
                    key,
                    system_id,
                    f"t.{key}",
                    category,
                    confidence,
                    NOW,
                    status,
                    NOW if decided else None,
                    "user:dpo" if decided else None,
                ),
            )


def _declared(dsn: str, rows: list[tuple[str, str, float]]) -> None:
    record_proposals(
        dsn,
        [
            {
                "node_key": key,
                "category": category,
                "declared": declared,
                "calibrated": min(declared, UNTRUSTED_CEILING),
                "prompt_sha256": "a" * 64,
            }
            for key, category, declared in rows
        ],
    )


def _sixty(category: str, declared: float, right_every: int) -> tuple[list, list]:
    keys = [f"{category}-{n}" for n in range(60)]
    queue = [
        (
            k,
            category,
            min(declared, UNTRUSTED_CEILING),
            "accepted" if n % right_every == 0 else "rejected",
        )
        for n, k in enumerate(keys)
    ]
    return queue, [(k, category, declared) for k in keys]


def test_the_curve_is_fitted_on_the_declared_confidence_not_the_queued_one(
    migrated_db: str,
) -> None:
    """The queue holds 0.8 (capped); the model said 0.95. The curve must learn from 0.95."""
    queue, declared = _sixty("financial_data", 0.95, right_every=2)
    _queue(migrated_db, queue)
    _declared(migrated_db, declared)
    calibrator = refit(migrated_db, now=NOW)
    assert calibrator.calibrate("financial_data", 0.95) == pytest.approx(0.5)
    assert calibrator.calibrate("financial_data", 0.8) == pytest.approx(0.5)


def test_the_fitted_curve_is_stored_and_read_back(migrated_db: str) -> None:
    queue, declared = _sixty("personal_data", 0.9, right_every=1)
    _queue(migrated_db, queue)
    _declared(migrated_db, declared)
    refit(migrated_db, now=NOW)
    assert stored_calibrator(migrated_db).calibrate("personal_data", 0.9) == pytest.approx(1.0)


def test_pending_decisions_are_not_labels(migrated_db: str) -> None:
    """A proposal nobody reviewed yet says nothing about whether the model was right."""
    queue, declared = _sixty("personal_data", 0.9, right_every=1)
    pending = [(k, c, conf, "pending") for k, c, conf, _ in queue]
    _queue(migrated_db, pending)
    _declared(migrated_db, declared)
    assert refit(migrated_db, now=NOW).calibrate("personal_data", 0.95) == UNTRUSTED_CEILING


def test_the_drift_reads_the_last_thirty_days(migrated_db: str) -> None:
    queue, declared = _sixty("contact_data", 0.9, right_every=4)
    _queue(migrated_db, queue)
    _declared(migrated_db, declared)
    assert drift(migrated_db, now=NOW) == {"contact_data": pytest.approx(0.25)}


def test_the_classifier_records_its_declared_confidences(migrated_db: str) -> None:
    reply = {"items": [{"key": "k1", "category": "financial_data", "confidence": 0.93}]}
    gateway = postgres_gateway(migrated_db, FakeBackend.of([json.dumps(reply)]))
    classifier = SemanticClassifier(
        gateway,
        stored_calibrator(migrated_db),
        record=lambda rows: record_proposals(migrated_db, rows),
    )
    classifier.propose([ColumnContext("k1", "amount_cents", "bigint", "billing.invoices", ())])
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT declared, calibrated FROM argos.ai_proposals WHERE node_key = 'k1'"
        ).fetchone()
    assert row is not None and float(row[0]) == pytest.approx(0.93)
    assert float(row[1]) == pytest.approx(UNTRUSTED_CEILING)
