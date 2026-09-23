"""ADR-0008 · the audited inventory of synthetic subjects and the client's own actions."""

import importlib.util
from types import ModuleType

import psycopg
import pymysql
import pytest

from argos_challenges.store import create_campaign
from argos_challenges.synthetic import (
    SyntheticError,
    authorize_injection,
    confirm_exercise,
    confirm_injection,
    confirm_revert,
    generate_subjects,
    pending_reversions,
    register_subjects,
)
from argos_common.journal_pg import PostgresJournal

from .sources import ROOT

pytestmark = pytest.mark.integration

SEED = "test-campaign"
REVIEWER = "user:dpo"
CLIENT = "user:client-dba"
SYSTEM = "00000000-0000-4000-8000-000000000001"
CLINIC_DSN = "postgresql://owner@127.0.0.1:55433/clinic"
BILLING = {"host": "127.0.0.1", "port": 53306, "user": "root", "password": ""}


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "demo_client_actions", ROOT / "tools" / "demo_client_actions.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _authorised(dsn: str) -> tuple[str, str]:
    subject = generate_subjects(SEED, 1)[0]
    register_subjects(dsn, None, [subject])
    injection = authorize_injection(
        dsn,
        subject.id,
        SYSTEM,
        "clinic.patients",
        "SQL del cliente",
        "DELETE FROM clinic.patients WHERE national_id = :national_id",
        REVIEWER,
    )
    return subject.id, injection


def test_the_inventory_keeps_hashes_and_never_the_clear_values(migrated_db: str) -> None:
    subject = generate_subjects(SEED, 2)[0]
    assert register_subjects(migrated_db, None, generate_subjects(SEED, 2)) == 2
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT value_hashes::text, markers::text FROM argos.synthetic_subjects WHERE id = %s",
            (subject.id,),
        ).fetchone()
    assert row is not None
    stored = row[0] + row[1]
    assert subject.value_hashes["national_id"] in stored
    for value in subject.markers.values():
        assert value not in stored


def test_only_a_person_authorises_and_only_with_a_revert_procedure(migrated_db: str) -> None:
    subject = generate_subjects(SEED, 1)[0]
    register_subjects(migrated_db, None, [subject])
    with pytest.raises(SyntheticError, match="person"):
        authorize_injection(
            migrated_db, subject.id, SYSTEM, "clinic.patients", "SQL", "DELETE ...", "system:robot"
        )
    with pytest.raises(SyntheticError, match="revert"):
        authorize_injection(
            migrated_db, subject.id, SYSTEM, "clinic.patients", "SQL", "   ", REVIEWER
        )


def test_the_confirmations_are_written_once_and_land_in_the_journal(migrated_db: str) -> None:
    _, injection = _authorised(migrated_db)
    confirm_injection(migrated_db, injection, CLIENT)
    confirm_exercise(migrated_db, injection, "erasure", CLIENT)
    assert pending_reversions(migrated_db) and pending_reversions(migrated_db)[0]["id"] == injection
    confirm_revert(migrated_db, injection, CLIENT)
    assert pending_reversions(migrated_db) == []
    with pytest.raises(SyntheticError, match="already confirmed"):
        confirm_injection(migrated_db, injection, "user:another")
    actions = [
        entry.action
        for entry in PostgresJournal(migrated_db).read(1, 100)
        if entry.action.startswith("synthetic.")
    ]
    assert actions == [
        "synthetic.generate",
        "synthetic.authorize",
        "synthetic.injected",
        "synthetic.exercised",
        "synthetic.revert",
    ]


def test_an_unknown_right_or_injection_is_rejected(migrated_db: str) -> None:
    _, injection = _authorised(migrated_db)
    with pytest.raises(SyntheticError, match="right"):
        confirm_exercise(migrated_db, injection, "portability", CLIENT)
    with pytest.raises(SyntheticError, match="unknown synthetic injection"):
        confirm_injection(migrated_db, "00000000-0000-4000-8000-0000000000ff", CLIENT)


def test_the_client_confirms_in_order_and_each_step_once(migrated_db: str) -> None:
    # A reversion or an exercise before the injection would let a campaign seal on nothing.
    _, injection = _authorised(migrated_db)
    with pytest.raises(SyntheticError, match="not injected"):
        confirm_revert(migrated_db, injection, CLIENT)
    with pytest.raises(SyntheticError, match="not injected"):
        confirm_exercise(migrated_db, injection, "erasure", CLIENT)
    confirm_injection(migrated_db, injection, CLIENT)
    confirm_exercise(migrated_db, injection, "erasure", CLIENT)
    # Another right of the same subject is a new exercise; the same right again is not.
    confirm_exercise(migrated_db, injection, "access", CLIENT)
    with pytest.raises(SyntheticError, match="already confirmed"):
        confirm_exercise(migrated_db, injection, "access", CLIENT)
    confirm_revert(migrated_db, injection, CLIENT)
    with pytest.raises(SyntheticError, match="already confirmed"):
        confirm_revert(migrated_db, injection, CLIENT)


def test_an_injection_is_authorised_only_for_a_subject_of_its_campaign(migrated_db: str) -> None:
    campaign = create_campaign(migrated_db, "Campaña del sujeto", {}, "user:manager")
    other = create_campaign(migrated_db, "Otra campaña", {}, "user:manager")
    subject = generate_subjects(SEED, 1)[0]
    register_subjects(migrated_db, other, [subject])
    arguments = (subject.id, SYSTEM, "clinic.patients", "SQL", "DELETE ...", REVIEWER)
    with pytest.raises(SyntheticError, match="does not belong"):
        authorize_injection(migrated_db, *arguments, campaign_id=campaign)
    assert authorize_injection(migrated_db, *arguments, campaign_id=other)


def test_a_subject_row_cannot_be_changed_or_deleted(migrated_db: str) -> None:
    subject = generate_subjects(SEED, 1)[0]
    register_subjects(migrated_db, None, [subject])
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("DELETE FROM argos.synthetic_subjects WHERE id = %s", (subject.id,))


def _in_clinic(national_id: str) -> int:
    with psycopg.connect(CLINIC_DSN) as conn:
        row = conn.execute(
            "SELECT count(*) FROM clinic.patients WHERE national_id = %s", (national_id,)
        ).fetchone()
    return 0 if row is None else int(row[0])


def _in_billing(national_id: str) -> int:
    conn = pymysql.connect(**BILLING)  # type: ignore[arg-type]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM billing.patient_mirror WHERE dni_number = %s", (national_id,)
            )
            (count,) = cur.fetchone()
    finally:
        conn.close()
    return int(count)


def test_the_client_script_leaves_the_subject_planted_in_the_replica() -> None:
    script = _script()
    subject = script.generate_subjects(script.SEED, 1)[0]
    script.revert(subject)  # start from a clean source
    try:
        script.inject(subject)
        assert _in_clinic(subject.national_id) == 1
        assert _in_billing(subject.national_id) == 1
        script.exercise_erasure(subject)
        assert _in_clinic(subject.national_id) == 0
        assert _in_billing(subject.national_id) == 1  # the planted gap the challenge must find
    finally:
        script.revert(subject)
    assert _in_billing(subject.national_id) == 0


def test_whoever_authorised_the_injection_does_not_confirm_it(migrated_db: str) -> None:
    """SEC-008: the DPO who authorises and the client who confirms are never the same person."""
    _, injection_id = _authorised(migrated_db)
    with pytest.raises(SyntheticError, match="authorised"):
        confirm_injection(migrated_db, injection_id, REVIEWER)
