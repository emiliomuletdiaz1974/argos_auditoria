"""ADR-0008 · a right is measured with the client's own dates, and a reversion is checked.

Security review F09-02: the term of a right used to be the time between two clicks of the console,
any campaign's injection counted, the dates could be rewritten (SEC-014), and a confirmed
reversion was believed without looking (SEC-015).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from temporalio.exceptions import ApplicationError

from argos_challenges.activities import ChallengeActivities
from argos_challenges.store import create_campaign, pin_campaign
from argos_challenges.synthetic import (
    SyntheticError,
    SyntheticSubject,
    authorize_injection,
    confirm_exercise,
    confirm_injection,
    confirm_revert,
    generate_subjects,
    register_subjects,
)
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore

from .inventory_helpers import probe_runner, scan_and_ingest, secret_store
from .test_synthetic_subjects import _script

pytestmark = pytest.mark.integration

MANAGER = "user:campaign-manager"
DPO = "user:dpo"
CLIENT = "user:client-dba"
NOW = datetime.now(UTC)


def _campaign(dsn: str, seed: str) -> tuple[str, SyntheticSubject]:
    campaign_id = create_campaign(dsn, f"Campaña {seed}", {}, MANAGER)
    subject = generate_subjects(seed, 1)[0]
    register_subjects(dsn, campaign_id, [subject])
    return campaign_id, subject


def _injected(dsn: str, campaign_id: str, subject: SyntheticSubject, system_id: str) -> str:
    injection = authorize_injection(
        dsn,
        subject.id,
        system_id,
        "clinic.patients",
        "INSERT",
        "DELETE por id",
        DPO,
        campaign_id=campaign_id,
    )
    confirm_injection(dsn, injection, CLIENT)
    return injection


def _access_unit(campaign_id: str, system_id: str) -> dict[str, Any]:
    return {
        "unit_id": "c" * 64,
        "campaign_id": campaign_id,
        "system_id": system_id,
        "probe": {
            "kind": "inventory_query",
            "target": "argos",
            "statement": None,
            "params": {"query": "access_request_days"},
        },
        "evidence": {"capture": ["counts"]},
    }


def _days(dsn: str, campaign_id: str, system_id: str) -> Any:
    activities = ChallengeActivities(dsn, secret_store())
    return activities._internal_probe(_access_unit(campaign_id, system_id))["data"].get("count")


# ---------- SEC-014 · the term is the client's, of this campaign, and written once ----------


def test_the_term_is_the_one_the_client_declares_not_the_clicks(migrated_db: str) -> None:
    system_id = "00000000-0000-4000-8000-000000000001"
    campaign_id, subject = _campaign(migrated_db, "term-40")
    injection = _injected(migrated_db, campaign_id, subject, system_id)
    # Both confirmations arrive within a minute; the request was answered after 40 days.
    confirm_exercise(
        migrated_db,
        injection,
        "access",
        CLIENT,
        requested_at=NOW - timedelta(days=41),
        answered_at=NOW - timedelta(days=1),
    )
    assert _days(migrated_db, campaign_id, system_id) == 40


def test_another_campaigns_exercise_does_not_count(migrated_db: str) -> None:
    system_id = "00000000-0000-4000-8000-000000000001"
    measured, subject = _campaign(migrated_db, "term-other")
    injection = _injected(migrated_db, measured, subject, system_id)
    confirm_exercise(
        migrated_db,
        injection,
        "access",
        CLIENT,
        requested_at=NOW - timedelta(days=3),
        answered_at=NOW - timedelta(days=1),
    )
    unrelated = create_campaign(migrated_db, "Campaña sin sujeto", {}, MANAGER)
    assert _days(migrated_db, unrelated, system_id) is None  # inconclusive, never borrowed


@pytest.mark.parametrize(
    ("requested", "answered", "message"),
    [
        (NOW + timedelta(days=1), NOW + timedelta(days=2), "future"),
        (NOW - timedelta(days=1), NOW - timedelta(days=5), "before"),
    ],
)
def test_the_client_dates_are_checked(
    migrated_db: str, requested: datetime, answered: datetime, message: str
) -> None:
    campaign_id, subject = _campaign(migrated_db, f"dates-{message}")
    injection = _injected(migrated_db, campaign_id, subject, "00000000-0000-4000-8000-000000000001")
    with pytest.raises(SyntheticError, match=message):
        confirm_exercise(
            migrated_db, injection, "access", CLIENT, requested_at=requested, answered_at=answered
        )


def test_the_dates_cannot_be_rewritten(migrated_db: str) -> None:
    campaign_id, subject = _campaign(migrated_db, "rewrite")
    injection = _injected(migrated_db, campaign_id, subject, "00000000-0000-4000-8000-000000000001")
    confirm_exercise(
        migrated_db,
        injection,
        "access",
        CLIENT,
        requested_at=NOW - timedelta(days=2),
        answered_at=NOW - timedelta(days=1),
    )
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            "UPDATE argos.synthetic_exercises SET answered_at = requested_at "
            "WHERE injection_id = %s",
            (injection,),
        )
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            "UPDATE argos.synthetic_injections SET injected_at = now() - interval '90 days' "
            "WHERE id = %s",
            (injection,),
        )


def test_a_subject_always_belongs_to_a_campaign(migrated_db: str) -> None:
    with pytest.raises(SyntheticError, match="campaign"):
        register_subjects(migrated_db, None, generate_subjects("orphan", 1))


# ---------- SEC-015 · the reversion is looked for before the seal ----------


@pytest.fixture
def injected_clinic(migrated_db: str) -> Any:
    """A campaign with its subject injected for real in the simulated clinical source."""
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    classify_new_columns(store, probe_runner(migrated_db), system_id)
    activities = ChallengeActivities(migrated_db, secret_store())
    campaign_id = create_campaign(migrated_db, "Campaña de reversión", {}, MANAGER)
    snapshot = activities._snapshot(campaign_id)
    pin_campaign(
        migrated_db,
        campaign_id,
        snapshot_id=snapshot.id,
        snapshot_hash=snapshot.content_hash,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    script = _script()
    subject = script.generate_subjects(script.SEED, 1)[0]
    register_subjects(migrated_db, campaign_id, [subject])
    script.revert(subject)  # start from a clean source
    script.inject(subject)
    injection = _injected(migrated_db, campaign_id, subject, system_id)
    try:
        yield activities, campaign_id, injection, script, subject
    finally:
        script.revert(subject)


def test_a_confirmed_reversion_with_the_subject_still_there_is_not_sealed(
    injected_clinic: Any,
) -> None:
    activities, campaign_id, injection, _, _ = injected_clinic
    confirm_revert(activities._dsn, injection, CLIENT)  # confirmed, but nothing was undone
    check = asyncio.run(activities.check_reversions(campaign_id))
    assert check["pending"] == [] and check["remaining"]
    assert {row["column"] for row in check["remaining"]} >= {"clinic.patients.national_id"}
    with pytest.raises(ApplicationError) as error:
        asyncio.run(activities.seal(campaign_id))
    assert error.value.type == "ReversionNotVerified"


def test_a_reversion_that_really_happened_lets_the_campaign_seal(injected_clinic: Any) -> None:
    activities, campaign_id, injection, script, subject = injected_clinic
    check = asyncio.run(activities.check_reversions(campaign_id))
    assert check["pending"] == [injection]  # not even confirmed yet
    script.revert(subject)
    confirm_revert(activities._dsn, injection, CLIENT)
    check = asyncio.run(activities.check_reversions(campaign_id))
    assert check == {"pending": [], "remaining": [], "unverifiable": []}
