"""The client's side of the demo: injects, exercises and reverts synthetic subjects (ADR-0008).

**This script is not part of the product.** ARGOS never writes in a client system; in the
demo somebody has to play the client, and that is this script, with the owner credentials
of the simulated sources. It injects the subject in the clinical system and in the billing
replica, runs the erasure only in the clinical system, and leaves the subject in the
replica on purpose: that planted gap is what the effective-erasure challenge has to find
(F05-01).
"""

import argparse
import sys
from pathlib import Path

import psycopg
import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "challenge-engine"))

from argos_challenges.synthetic import SyntheticSubject, generate_subjects  # noqa: E402

CLINIC_DSN = "postgresql://owner@127.0.0.1:55433/clinic"
BILLING = {"host": "127.0.0.1", "port": 53306, "user": "root", "password": ""}
SEED = "demo-campaign"
PATIENT_ID = 900001
DIAGNOSIS = "Z00.0"

INJECT_CLINIC = (
    "INSERT INTO clinic.patients (id, national_id, full_name, birth_date, created_at) "
    "VALUES (%(id)s, %(national_id)s, %(full_name)s, DATE '1980-05-05', now()) "
    "ON CONFLICT (id) DO NOTHING",
    "INSERT INTO clinic.patient_documents "
    "(patient_id, dni_number, iban, diagnosis_code, email) "
    "VALUES (%(id)s, %(national_id)s, %(iban)s, %(diagnosis)s, %(email)s) "
    "ON CONFLICT (patient_id) DO NOTHING",
)
ERASE_CLINIC = (
    "DELETE FROM clinic.patient_documents WHERE patient_id = %(id)s",
    "DELETE FROM clinic.patients WHERE id = %(id)s",
)
INJECT_BILLING = (
    "INSERT IGNORE INTO billing.patient_mirror "
    "(id, dni_number, iban, diagnosis_code, email) VALUES (%s, %s, %s, %s, %s)"
)
ERASE_BILLING = "DELETE FROM billing.patient_mirror WHERE id = %s"


def _params(subject: SyntheticSubject) -> dict[str, object]:
    return {
        "id": PATIENT_ID,
        "national_id": subject.national_id,
        "full_name": subject.full_name,
        "iban": subject.iban,
        "email": subject.email,
        "diagnosis": DIAGNOSIS,
    }


def _clinic(statements: tuple[str, ...], subject: SyntheticSubject) -> None:
    with psycopg.connect(CLINIC_DSN) as conn:
        for statement in statements:
            conn.execute(statement, _params(subject))


def _billing(statement: str, args: tuple[object, ...]) -> None:
    conn = pymysql.connect(**BILLING)  # type: ignore[arg-type]
    try:
        with conn.cursor() as cur:
            cur.execute(statement, args)
        conn.commit()
    finally:
        conn.close()


def inject(subject: SyntheticSubject) -> None:
    _clinic(INJECT_CLINIC, subject)
    _billing(
        INJECT_BILLING,
        (PATIENT_ID, subject.national_id, subject.iban, DIAGNOSIS, subject.email),
    )


def exercise_erasure(subject: SyntheticSubject) -> None:
    """The client honours the erasure request: only in the clinical system, as in real life."""
    _clinic(ERASE_CLINIC, subject)


def erase_from_replica(subject: SyntheticSubject) -> None:
    """The client finally honours the erasure in the billing replica it had missed."""
    _billing(ERASE_BILLING, (PATIENT_ID,))


def revert(subject: SyntheticSubject) -> None:
    _clinic(ERASE_CLINIC, subject)
    _billing(ERASE_BILLING, (PATIENT_ID,))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inject", "erase", "erase-replica", "revert", "show"])
    parser.add_argument("--seed", default=SEED)
    args = parser.parse_args(argv)
    subject = generate_subjects(args.seed, 1)[0]
    if args.action == "inject":
        inject(subject)
    elif args.action == "erase":
        exercise_erasure(subject)
    elif args.action == "erase-replica":
        erase_from_replica(subject)
    elif args.action == "revert":
        revert(subject)
    print(f"{args.action}: {subject.national_id} ({subject.email})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
