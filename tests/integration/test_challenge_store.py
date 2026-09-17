"""ARG-043/046/047 · campaigns, units, verdicts and approvals: idempotent and immutable."""

from typing import Any

import psycopg
import pytest

from argos_challenges.evaluator import evaluate
from argos_challenges.store import (
    CampaignStateError,
    campaign_record,
    create_campaign,
    grant_approval,
    persist_verdict,
    pin_campaign,
    request_approval,
    save_units,
    set_status,
)
from argos_common.journal_pg import PostgresJournal

pytestmark = pytest.mark.integration

MANAGER = "user:campaign-manager"
DPO = "user:dpo"
SECOND_DPO = "user:dpo-2"
SYSTEM = "00000000-0000-4000-8000-000000000001"
SNAPSHOT = "00000000-0000-4000-8000-0000000000aa"
UNIT: dict[str, Any] = {
    "unit_id": "d1c0ffee" * 8,
    "challenge_id": "sec-encryption-in-transit",
    "challenge_version": "1.0",
    "obligation": "OBL-RGPD-32-3",
    "system_id": SYSTEM,
    "node_key": "k-node-0001",
    "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
    "sampling": None,
}
PROBE = {"ok": True, "data": {"rows": [{"ssl": "off"}]}}


def _campaign(dsn: str) -> str:
    return create_campaign(dsn, "Campaña de prueba", {"system_ids": [SYSTEM]}, MANAGER)


def _pinned(dsn: str) -> str:
    campaign_id = _campaign(dsn)
    pin_campaign(
        dsn,
        campaign_id,
        snapshot_id=SNAPSHOT,
        snapshot_hash="a" * 64,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    save_units(dsn, campaign_id, [UNIT])
    return campaign_id


def test_a_campaign_is_created_pinned_and_readable(migrated_db: str) -> None:
    campaign_id = _pinned(migrated_db)
    record = campaign_record(migrated_db, campaign_id)
    assert record["status"] == "pinned"
    assert record["snapshot_id"] == SNAPSHOT
    assert record["ontology_version"] == "1.0.0"
    assert record["units"] == 1
    actions = [e.action for e in PostgresJournal(migrated_db).read(1, 100)]
    assert "campaign.create" in actions and "campaign.pin" in actions


def test_a_campaign_is_pinned_once(migrated_db: str) -> None:
    campaign_id = _pinned(migrated_db)
    with pytest.raises(CampaignStateError, match="pinned"):
        pin_campaign(
            migrated_db,
            campaign_id,
            snapshot_id=SNAPSHOT,
            snapshot_hash="c" * 64,
            ontology_version="2.0.0",
            library_version="1.0.0",
            library_sha256="b" * 64,
            applicability_run=None,
        )


def test_the_same_unit_gives_one_verdict_however_many_times_it_runs(migrated_db: str) -> None:
    campaign_id = _pinned(migrated_db)
    verdict = evaluate(UNIT, PROBE)
    first, created = persist_verdict(migrated_db, campaign_id, UNIT, verdict, probe_journal_seq=1)
    again, created_again = persist_verdict(
        migrated_db, campaign_id, UNIT, verdict, probe_journal_seq=2
    )
    assert created and not created_again and first == again
    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute(
            "SELECT result, verdict_hash, probe_journal_seq FROM argos.verdicts "
            "WHERE campaign_id = %s",
            (campaign_id,),
        ).fetchall()
    assert rows == [("non_compliant", verdict.hash, 1)]
    emitted = [e for e in PostgresJournal(migrated_db).read(1, 100) if e.action == "verdict.emit"]
    assert len(emitted) == 1


def test_a_verdict_is_immutable(migrated_db: str) -> None:
    campaign_id = _pinned(migrated_db)
    persist_verdict(migrated_db, campaign_id, UNIT, evaluate(UNIT, PROBE), probe_journal_seq=1)
    for statement in (
        "UPDATE argos.verdicts SET result = 'compliant'",
        "DELETE FROM argos.verdicts",
        "TRUNCATE argos.verdicts",
    ):
        with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
            conn.execute(statement)


def test_an_unknown_result_is_refused_by_the_database(migrated_db: str) -> None:
    campaign_id = _pinned(migrated_db)
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO argos.verdicts (id, campaign_id, unit_id, challenge_id, "
            "challenge_version, obligation, system_id, node_key, result, verdict, verdict_hash) "
            "VALUES (gen_random_uuid(), %s, 'u', 'c', '1.0', 'OBL-X', %s, 'k', 'maybe', '{}', %s)",
            (campaign_id, SYSTEM, "d" * 64),
        )


def test_a_gate_needs_its_request_and_counts_different_people(migrated_db: str) -> None:
    campaign_id = _pinned(migrated_db)
    with pytest.raises(CampaignStateError, match="requested"):
        grant_approval(migrated_db, campaign_id, "start", DPO)
    request_approval(migrated_db, campaign_id, "start", {"units": 1})
    granted, enough = grant_approval(migrated_db, campaign_id, "start", DPO)
    assert (granted, enough) == (1, True)
    with pytest.raises(CampaignStateError, match="already"):
        grant_approval(migrated_db, campaign_id, "start", DPO)

    request_approval(migrated_db, campaign_id, "sampling", {"units": 1})
    granted, enough = grant_approval(migrated_db, campaign_id, "sampling", DPO, needed=2)
    assert (granted, enough) == (1, False)
    granted, enough = grant_approval(migrated_db, campaign_id, "sampling", SECOND_DPO, needed=2)
    assert (granted, enough) == (2, True)
    actions = [e.action for e in PostgresJournal(migrated_db).read(1, 200)]
    assert actions.count("approval.request") == 2 and actions.count("approval.grant") == 3


def test_requesting_the_same_gate_twice_keeps_the_first_request(migrated_db: str) -> None:
    campaign_id = _pinned(migrated_db)
    request_approval(migrated_db, campaign_id, "start", {"units": 1})
    request_approval(migrated_db, campaign_id, "start", {"units": 99})
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT payload::text FROM argos.approval_requests WHERE campaign_id = %s",
            (campaign_id,),
        ).fetchone()
    assert row is not None and '"units": 1' in row[0]


def test_the_status_moves_only_through_declared_states(migrated_db: str) -> None:
    campaign_id = _pinned(migrated_db)
    set_status(migrated_db, campaign_id, "running")
    assert campaign_record(migrated_db, campaign_id)["status"] == "running"
    with pytest.raises(CampaignStateError, match="status"):
        set_status(migrated_db, campaign_id, "finished")
