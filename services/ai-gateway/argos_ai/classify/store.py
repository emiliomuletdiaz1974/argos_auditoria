"""The calibration against PostgreSQL: record, refit, read back and measure drift (ARG-055).

The refit is the nightly job: every decision the DPO took since the last one is a new label. The
scheduling itself belongs to operation; this module is what it runs.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from argos_ai.classify.calibration import (
    Calibrator,
    Decision,
    precision_by_category,
)
from argos_common.journal_pg import PostgresJournal

ACTOR = "system:ai-calibration"
_DECISIONS = (
    "SELECT q.proposed_category, p.declared, q.status, q.decided_at "
    "FROM argos.review_queue q JOIN argos.ai_proposals p "
    "ON p.node_key = q.node_key AND p.category = q.proposed_category "
    "WHERE q.status IN ('accepted', 'rejected')"
)
_RECORD = (
    "INSERT INTO argos.ai_proposals (node_key, category, declared, calibrated, prompt_sha256) "
    "VALUES (%(node_key)s, %(category)s, %(declared)s, %(calibrated)s, %(prompt_sha256)s) "
    "ON CONFLICT (node_key) DO UPDATE SET category = EXCLUDED.category, "
    "declared = EXCLUDED.declared, calibrated = EXCLUDED.calibrated, "
    "prompt_sha256 = EXCLUDED.prompt_sha256, proposed_at = now()"
)
_STORE = (
    "INSERT INTO argos.ai_calibration (category, pairs, curve, fitted_at) VALUES (%s, %s, %s, %s) "
    "ON CONFLICT (category) DO UPDATE SET pairs = EXCLUDED.pairs, curve = EXCLUDED.curve, "
    "fitted_at = EXCLUDED.fitted_at"
)


def record_proposals(dsn: str, rows: Sequence[dict[str, Any]]) -> None:
    """What the model declared, per column: the raw material of the next curve."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.executemany(_RECORD, list(rows))


def load_decisions(dsn: str) -> list[Decision]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(_DECISIONS).fetchall()
    return [
        Decision(str(category), float(declared), str(status) == "accepted", decided_at)
        for category, declared, status, decided_at in rows
    ]


def refit(dsn: str, now: datetime | None = None) -> Calibrator:
    """Fit a new curve per category from every decided proposal, store it and journal it."""
    moment = now or datetime.now(UTC)
    decisions = load_decisions(dsn)
    calibrator = Calibrator.fit(decisions)
    curves = calibrator.curves()
    pairs: dict[str, int] = {}
    for decision in decisions:
        pairs[decision.category] = pairs.get(decision.category, 0) + 1
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM argos.ai_calibration")
        for category, blocks in sorted(curves.items()):
            conn.execute(_STORE, (category, pairs[category], Jsonb(blocks), moment))
    PostgresJournal(dsn).append(
        ACTOR,
        "ai.calibration_refit",
        {"categories": sorted(curves), "decisions": len(decisions)},
    )
    return calibrator


def stored_calibrator(dsn: str) -> Calibrator:
    """The curves of the last refit; none yet means the capped identity everywhere."""
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT category, curve FROM argos.ai_calibration").fetchall()
    return Calibrator.from_curves({str(category): curve for category, curve in rows})


def drift(dsn: str, now: datetime | None = None) -> dict[str, float]:
    """Precision per category over the last thirty days: the signal ARG-059 publishes."""
    return precision_by_category(load_decisions(dsn), now=now)
