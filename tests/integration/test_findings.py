"""ARG-048 · findings against the database: deduplication, escalation and documented exceptions."""

from datetime import date, timedelta
from typing import Any

import psycopg
import pytest

from argos_challenges.evaluator import evaluate
from argos_challenges.findings import (
    FindingError,
    expire_risk_acceptances,
    fingerprint,
    open_or_recur,
    transition,
)
from argos_challenges.store import create_campaign, persist_verdict, pin_campaign
from argos_common.journal_pg import PostgresJournal

pytestmark = pytest.mark.integration

MANAGER = "user:campaign-manager"
DPO = "user:dpo"
SYSTEM = "00000000-0000-4000-8000-000000000001"
UNIT: dict[str, Any] = {
    "unit_id": "f" * 64,
    "challenge_id": "sec-encryption-in-transit",
    "challenge_version": "1.0",
    "obligation": "OBL-RGPD-32-3",
    "system_id": SYSTEM,
    "node_key": "k-node-0001",
    "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
    "sampling": None,
    "severity": "medium",
}
PROBE = {"ok": True, "data": {"rows": [{"ssl": "off"}]}}


def _campaign(dsn: str, name: str) -> str:
    campaign_id = create_campaign(dsn, name, {}, MANAGER)
    pin_campaign(
        dsn,
        campaign_id,
        snapshot_id=None,
        snapshot_hash=None,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    return campaign_id


def _finding(dsn: str, campaign_id: str, unit: dict[str, Any] | None = None) -> dict[str, Any]:
    work = dict(unit or UNIT)
    work["campaign_id"] = campaign_id
    work["unit_id"] = f"{campaign_id[:8]}{work['unit_id'][8:]}"
    verdict = evaluate(work, PROBE)
    verdict_id, _ = persist_verdict(dsn, campaign_id, work, verdict)
    return open_or_recur(dsn, campaign_id, work, verdict, verdict_id)


def test_the_same_problem_in_the_same_campaign_is_one_finding(migrated_db: str) -> None:
    campaign_id = _campaign(migrated_db, "Campaña 1")
    first = _finding(migrated_db, campaign_id)
    again = _finding(migrated_db, campaign_id)
    assert first["created"] is True and again["created"] is False
    assert first["id"] == again["id"]
    assert again["occurrences"] == 1  # the same campaign does not count twice


def test_three_campaigns_raise_the_severity_once(migrated_db: str) -> None:
    findings = [_finding(migrated_db, _campaign(migrated_db, f"Campaña {n}")) for n in range(3)]
    assert [f["occurrences"] for f in findings] == [1, 2, 3]
    assert [f["severity"] for f in findings] == ["medium", "medium", "high"]
    assert len({f["id"] for f in findings}) == 1
    actions = [e.action for e in PostgresJournal(migrated_db).read(1, 500)]
    assert actions.count("finding.open") == 1 and actions.count("finding.recur") == 2


def test_a_finding_closes_only_through_the_verification(migrated_db: str) -> None:
    campaign_id = _campaign(migrated_db, "Campaña de cierre")
    finding = _finding(migrated_db, campaign_id)
    with pytest.raises(FindingError, match="only a re-run"):
        transition(migrated_db, finding["id"], "closed_compliant", DPO)
    transition(migrated_db, finding["id"], "in_remediation", DPO)
    transition(migrated_db, finding["id"], "pending_verification", DPO)
    transition(migrated_db, finding["id"], "closed_compliant", "system:remediation")
    with pytest.raises(FindingError, match="illegal transition"):
        transition(migrated_db, finding["id"], "in_remediation", DPO)


def test_accepting_a_risk_is_documented_and_expires(migrated_db: str) -> None:
    campaign_id = _campaign(migrated_db, "Campaña de riesgo")
    finding = _finding(migrated_db, campaign_id)
    with pytest.raises(FindingError, match="justification"):
        transition(migrated_db, finding["id"], "risk_accepted", DPO)
    yesterday = date.today() - timedelta(days=1)
    transition(
        migrated_db,
        finding["id"],
        "risk_accepted",
        DPO,
        note="Migración del sistema prevista para el trimestre siguiente.",
        risk_expiry=yesterday,
    )
    assert expire_risk_acceptances(migrated_db) == [finding["id"]]
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT status FROM argos.findings WHERE id = %s", (finding["id"],)
        ).fetchone()
    assert row is not None and row[0] == "reopened"


def test_a_reopened_finding_that_comes_back_is_not_a_new_occurrence(migrated_db: str) -> None:
    campaign_id = _campaign(migrated_db, "Campaña de reapertura")
    finding = _finding(migrated_db, campaign_id)
    transition(migrated_db, finding["id"], "in_remediation", DPO)
    transition(migrated_db, finding["id"], "pending_verification", DPO)
    transition(migrated_db, finding["id"], "closed_compliant", "system:remediation")
    again = _finding(migrated_db, campaign_id)
    assert again["id"] == finding["id"]
    assert again["occurrences"] == 1
    assert again["status"] == "reopened"


def test_the_fingerprint_is_unique_in_the_database(migrated_db: str) -> None:
    campaign_id = _campaign(migrated_db, "Campaña de huella")
    finding = _finding(migrated_db, campaign_id)
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT fingerprint FROM argos.findings WHERE id = %s", (finding["id"],)
        ).fetchone()
    assert row is not None
    assert row[0] == fingerprint(UNIT["challenge_id"], UNIT["node_key"])
