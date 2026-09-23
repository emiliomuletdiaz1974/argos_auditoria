"""F09-23 · a sealed campaign holds only what was planned, approved and evaluated by the engine.

Findings of the security review F09-02: SEC-007 (a verdict from a unit nobody planned), SEC-013
(what the seal covers), SEC-016 (a campaign resealed after the fact) and SEC-037 (an OPA outage
frozen as `inconclusive`).
"""

from typing import Any

import psycopg
import pytest
from temporalio.exceptions import ApplicationError

from argos_challenges import activities as activities_module
from argos_challenges.activities import ChallengeActivities
from argos_challenges.evaluator import evaluate
from argos_challenges.seal import JOURNAL_ACTION, SealError, seal_campaign, verify_seal
from argos_challenges.store import (
    CampaignStateError,
    create_campaign,
    grant_approval,
    persist_verdict,
    pin_campaign,
    request_approval,
    save_units,
    set_status,
)
from argos_common.journal_pg import PostgresJournal
from argos_ontology.opa import OpaError

from .inventory_helpers import secret_store

pytestmark = pytest.mark.integration

MANAGER = "user:campaign-manager"
DPO = "user:dpo"
SYSTEM = "01920000-0000-7000-8000-00000000c0de"


def _unit(campaign_id: str, name: str = "sec-integrity", **extra: Any) -> dict[str, Any]:
    unit = {
        "unit_id": f"{name:x<64}"[:64],
        "campaign_id": campaign_id,
        "challenge_id": name,
        "challenge_version": "1.0",
        "obligation": "OBL-RGPD-32-1",
        "system_id": SYSTEM,
        "node_key": f"k-{name}",
        "probe": {"kind": "count", "target": "t", "statement": None, "params": {}},
        "criterion": {"threshold": {"field": "count", "operator": "==", "value": 0}},
        "evidence": {"capture": ["count"], "minimisation": "Solo recuentos."},
        "severity": "high",
        "sampling": None,
        "needs_approval": False,
        "preconditions": [],
    }
    unit.update(extra)
    return unit


def _campaign(dsn: str, *, running: bool = True) -> tuple[str, dict[str, Any]]:
    campaign_id = create_campaign(dsn, "Campaña íntegra", {}, MANAGER)
    pin_campaign(
        dsn,
        campaign_id,
        snapshot_id=None,
        snapshot_hash=None,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="c" * 64,
        applicability_run=None,
    )
    unit = _unit(campaign_id)
    save_units(dsn, campaign_id, [unit])
    if running:
        request_approval(dsn, campaign_id, "start", {"units": 1})
        grant_approval(dsn, campaign_id, "start", DPO, 1)
        set_status(dsn, campaign_id, "running")
    return campaign_id, unit


def _verdicts(dsn: str, campaign_id: str) -> int:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT count(*) FROM argos.verdicts WHERE campaign_id = %s", (campaign_id,)
        ).fetchone()
    return int(row[0]) if row else 0


PASSING = {"ok": True, "data": {"count": 0}, "journal_seq": None}


# ---------- SEC-007: only planned units become verdicts ----------


def test_a_unit_nobody_planned_leaves_no_verdict(migrated_db: str) -> None:
    campaign_id, unit = _campaign(migrated_db)
    forged = {**unit, "criterion": {"threshold": {"field": "count", "operator": ">=", "value": 0}}}
    activities = ChallengeActivities(migrated_db, secret_store(), opa_url="http://unused")
    with pytest.raises(ApplicationError, match="plan"):
        activities._decide(forged, PASSING)
    invented = _unit(campaign_id, "sec-invented")
    with pytest.raises(ApplicationError, match="plan"):
        activities._decide(invented, PASSING)
    assert _verdicts(migrated_db, campaign_id) == 0


def test_a_campaign_that_is_not_running_is_not_evaluated(migrated_db: str) -> None:
    campaign_id, unit = _campaign(migrated_db, running=False)
    activities = ChallengeActivities(migrated_db, secret_store(), opa_url="http://unused")
    with pytest.raises(ApplicationError, match="running"):
        activities._decide(unit, PASSING)
    assert _verdicts(migrated_db, campaign_id) == 0


def test_the_planned_unit_of_a_running_campaign_is_evaluated(migrated_db: str) -> None:
    campaign_id, unit = _campaign(migrated_db)
    activities = ChallengeActivities(migrated_db, secret_store(), opa_url="http://unused")
    answer = activities._decide(unit, PASSING)
    assert answer["result"] == "compliant" and _verdicts(migrated_db, campaign_id) == 1


def test_a_second_verdict_that_disagrees_is_an_error_not_silence(migrated_db: str) -> None:
    campaign_id, unit = _campaign(migrated_db)
    persist_verdict(migrated_db, campaign_id, unit, evaluate(unit, PASSING))
    other = evaluate(unit, {"ok": True, "data": {"count": 5}})
    with pytest.raises(CampaignStateError, match="different"):
        persist_verdict(migrated_db, campaign_id, unit, other)
    # the same verdict again is the retry of an activity, and it is fine
    persist_verdict(migrated_db, campaign_id, unit, evaluate(unit, PASSING))


# ---------- SEC-037: an OPA outage is retried, not frozen ----------


def test_an_opa_failure_is_retried_not_written_as_inconclusive(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign_id, unit = _campaign(migrated_db)
    opa_unit = {**unit, "criterion": {"opa": {"package": "argos.retention", "input_map": {}}}}
    with psycopg.connect(migrated_db) as conn:
        conn.execute(
            "UPDATE argos.campaign_units SET unit = %s WHERE campaign_id = %s AND unit_id = %s",
            (psycopg.types.json.Jsonb(opa_unit), campaign_id, unit["unit_id"]),
        )

    def down(*args: Any, **kwargs: Any) -> Any:
        raise OpaError("OPA is not answering")

    monkeypatch.setattr(activities_module, "opa_evaluate", down)
    activities = ChallengeActivities(migrated_db, secret_store(), opa_url="http://unused")
    with pytest.raises(ApplicationError) as raised:
        activities._decide(opa_unit, PASSING)
    assert raised.value.non_retryable is False
    assert _verdicts(migrated_db, campaign_id) == 0


# ---------- SEC-013, SEC-016: the seal ----------


def test_only_a_running_campaign_is_sealed(migrated_db: str) -> None:
    campaign_id, _ = _campaign(migrated_db, running=False)
    with pytest.raises((SealError, CampaignStateError)):
        seal_campaign(migrated_db, campaign_id)


def test_a_sealed_campaign_takes_no_new_verdict_and_keeps_its_seal(migrated_db: str) -> None:
    campaign_id, unit = _campaign(migrated_db)
    persist_verdict(migrated_db, campaign_id, unit, evaluate(unit, PASSING))
    seal_campaign(migrated_db, campaign_id)
    late = _unit(campaign_id, "sec-late")
    with pytest.raises(psycopg.Error):
        persist_verdict(migrated_db, campaign_id, late, evaluate(late, PASSING))
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.Error):
        conn.execute("UPDATE argos.campaigns SET seal = %s WHERE id = %s", ("0" * 64, campaign_id))
    assert verify_seal(migrated_db, campaign_id)


def test_a_second_seal_anchor_makes_the_seal_unverifiable(migrated_db: str) -> None:
    campaign_id, unit = _campaign(migrated_db)
    persist_verdict(migrated_db, campaign_id, unit, evaluate(unit, PASSING))
    seal_campaign(migrated_db, campaign_id)
    PostgresJournal(migrated_db).append(
        "system:campaign",
        JOURNAL_ACTION,
        {"campaign": campaign_id, "seal": "f" * 64, "verdicts": 9},
    )
    assert not verify_seal(migrated_db, campaign_id)


def test_the_seal_covers_approvals_and_the_plan(migrated_db: str) -> None:
    campaign_id, unit = _campaign(migrated_db)
    persist_verdict(migrated_db, campaign_id, unit, evaluate(unit, PASSING))
    seal_campaign(migrated_db, campaign_id)
    assert verify_seal(migrated_db, campaign_id)
    with psycopg.connect(migrated_db) as conn:
        conn.execute(
            'UPDATE argos.campaign_units SET unit = unit || \'{"severity": "low"}\'::jsonb '
            "WHERE campaign_id = %s",
            (campaign_id,),
        )
    assert not verify_seal(migrated_db, campaign_id)
