"""Synthetic subjects (ADR-0008).

ARGOS generates identities that are valid in format but impossible to confuse with a real person,
and keeps the audited inventory of where each one is injected. **It never writes in the client's
systems**: the client injects them and exercises the rights through its own channels, and confirms
each step; ARGOS only verifies, read-only, that the data is where it must be and gone where it must
be gone. Without the client's confirmation a challenge that needs a subject stays inconclusive.
"""

import hashlib
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from argos_common.errors import ArgosError
from argos_common.ids import uuid7
from argos_common.journal_pg import PostgresJournal
from argos_connector.validators import DNI_LETTERS

# Markers. The DNI range is never issued and sits above the one the simulated sources use (F03-00);
# the IBAN entity does not exist; example.invalid is reserved by RFC 2606.
SYNTHETIC_DNI_RANGE = (99992001, 99992999)
IBAN_ENTITY = "9999"
IBAN_BRANCH = "0002"
EMAIL_DOMAIN = "example.invalid"
EMAIL_PREFIX = "syn.subject"
NAME_PREFIX = "SYN "
# A subject is reproducible from its seed, id included: the same campaign generates the same people.
SUBJECT_NAMESPACE = uuid.UUID("6f0c7f34-3a1d-5c0f-9b0a-2f4a0d2f4c11")
RIGHTS = ("access", "erasure", "rectification")
JOURNAL_ACTOR = "system:synthetic"


class SyntheticError(ArgosError):
    """The synthetic subject flow was used out of order."""


@dataclass(frozen=True, slots=True)
class SyntheticSubject:
    id: str
    seed: str
    index: int
    full_name: str
    national_id: str
    iban: str
    email: str
    value_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def markers(self) -> dict[str, str]:
        return {
            "full_name": self.full_name,
            "national_id": self.national_id,
            "iban": self.iban,
            "email": self.email,
        }


def _digits(seed: str, index: int, size: int) -> int:
    material = hashlib.sha256(f"{seed}|{index}".encode()).hexdigest()
    return int(int(material, 16) % (10**size))


def _dni(seed: str, index: int) -> str:
    low, high = SYNTHETIC_DNI_RANGE
    number = low + _digits(seed, index, 8) % (high - low + 1)
    return f"{number:08d}{DNI_LETTERS[number % 23]}"


def _iban(seed: str, index: int) -> str:
    account = f"{IBAN_ENTITY}{IBAN_BRANCH}00{_digits(seed, index + 1000, 10):010d}"
    rearranged = f"{account}142800"  # ES = 14 28, check digits as 00 for the computation
    check = 98 - int(rearranged) % 97
    return f"ES{check:02d}{account}"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_subjects(seed: str, count: int) -> list[SyntheticSubject]:
    """Subjects for a campaign: the same seed always gives the same identities."""
    if count < 1:
        raise ValueError("count must be at least 1")
    subjects: list[SyntheticSubject] = []
    for index in range(count):
        national_id = _dni(seed, index)
        iban = _iban(seed, index)
        email = f"{EMAIL_PREFIX}{index}.{national_id[:8]}@{EMAIL_DOMAIN}"
        full_name = f"{NAME_PREFIX}Sujeto Sintetico {index}"
        markers = {
            "full_name": full_name,
            "national_id": national_id,
            "iban": iban,
            "email": email,
        }
        subjects.append(
            SyntheticSubject(
                id=str(uuid.uuid5(SUBJECT_NAMESPACE, f"{seed}|{index}")),
                seed=seed,
                index=index,
                full_name=full_name,
                national_id=national_id,
                iban=iban,
                email=email,
                value_hashes={name: _hash(value) for name, value in markers.items()},
            )
        )
    return subjects


def is_synthetic(value: object) -> bool:
    """Whether a value carries one of the synthetic markers."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text.endswith(f"@{EMAIL_DOMAIN}"):
        return True
    if text.startswith(NAME_PREFIX):
        return True
    if text.startswith("ES") and len(text) == 24 and text[4:8] == IBAN_ENTITY:
        return True
    low, high = SYNTHETIC_DNI_RANGE
    if len(text) == 9 and text[:8].isdigit():
        return low <= int(text[:8]) <= high
    return False


def client_package(
    subject: SyntheticSubject, injections: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """What the client receives: the clear values, the authorised points and how to undo them."""
    return {
        "subject_id": subject.id,
        "seed": subject.seed,
        "values": subject.markers,
        "value_hashes": dict(subject.value_hashes),
        "injections": [dict(injection) for injection in injections],
        "warning": (
            "Datos sintéticos generados por ARGOS. Inyéctelos solo en los puntos autorizados y "
            "revierta cada inyección al terminar la campaña."
        ),
    }


def _now() -> datetime:
    return datetime.now(UTC)


def register_subjects(
    dsn: str, campaign_id: str | None, subjects: Iterable[SyntheticSubject]
) -> int:
    """Record the generated subjects; the clear values never reach the database."""
    rows = [
        (
            subject.id,
            campaign_id,
            subject.seed,
            subject.index,
            Jsonb({"email_domain": EMAIL_DOMAIN, "dni_range": list(SYNTHETIC_DNI_RANGE)}),
            Jsonb(subject.value_hashes),
        )
        for subject in subjects
    ]
    if not rows:
        return 0
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO argos.synthetic_subjects "
                "(id, campaign_id, seed, subject_index, markers, value_hashes) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                rows,
            )
        journal.append(
            JOURNAL_ACTOR,
            "synthetic.generate",
            {"campaign_id": campaign_id, "subjects": len(rows)},
            conn=conn,
        )
    return len(rows)


def _person(actor: str, what: str) -> None:
    if not actor.startswith("user:"):
        raise SyntheticError(f"{what} is done by a person: the actor must be user:<sub>")


def authorize_injection(
    dsn: str,
    subject_id: str,
    system_id: str,
    point: str,
    method: str,
    revert_procedure: str,
    reviewer: str,
) -> str:
    """A DPO authorises one injection point. Nothing is injected by ARGOS."""
    _person(reviewer, "authorising an injection")
    if not revert_procedure.strip():
        raise SyntheticError("an injection is authorised only with its revert procedure")
    injection_id = str(uuid7())
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.synthetic_injections "
            "(id, subject_id, system_id, point, method, revert_procedure, authorized_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (injection_id, subject_id, system_id, point, method, revert_procedure, reviewer),
        )
        journal.append(
            reviewer,
            "synthetic.authorize",
            {"injection": injection_id, "subject": subject_id, "point": point},
            conn=conn,
        )
    return injection_id


def _confirm(
    dsn: str, injection_id: str, actor: str, action: str, sets: str, args: tuple[Any, ...]
) -> None:
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        # `sets` is a literal written in this module, never user input; the values are parameters.
        statement = f"UPDATE argos.synthetic_injections SET {sets} WHERE id = %s"  # noqa: S608
        updated = conn.execute(statement, (*args, injection_id)).rowcount
        if not updated:
            raise SyntheticError(f"unknown synthetic injection: {injection_id}")
        journal.append(actor, action, {"injection": injection_id}, conn=conn)


def confirm_injection(dsn: str, injection_id: str, confirmed_by: str) -> None:
    """The client says it injected the subject at the authorised point."""
    _person(confirmed_by, "confirming an injection")
    _confirm(
        dsn,
        injection_id,
        confirmed_by,
        "synthetic.injected",
        "injected_confirmed_by = %s, injected_at = %s",
        (confirmed_by, _now()),
    )


def confirm_exercise(dsn: str, injection_id: str, right: str, confirmed_by: str) -> None:
    """The client says it exercised a right of the subject through its own channel."""
    _person(confirmed_by, "confirming the exercise of a right")
    if right not in RIGHTS:
        raise SyntheticError(f"unknown right: {right!r}")
    _confirm(
        dsn,
        injection_id,
        confirmed_by,
        "synthetic.exercised",
        "exercised_right = %s, exercised_confirmed_by = %s, exercised_at = %s",
        (right, confirmed_by, _now()),
    )


def confirm_revert(dsn: str, injection_id: str, reverted_by: str) -> None:
    """The client says it undid the injection."""
    _person(reverted_by, "confirming a reversion")
    _confirm(
        dsn,
        injection_id,
        reverted_by,
        "synthetic.revert",
        "reverted_by = %s, reverted_at = %s",
        (reverted_by, _now()),
    )


def pending_reversions(dsn: str, campaign_id: str | None = None) -> list[dict[str, Any]]:
    """Injections confirmed and not reverted: a campaign is not sealed while any is left."""
    query = (
        "SELECT i.id::text, i.subject_id::text, i.system_id::text, i.point "
        "FROM argos.synthetic_injections i "
        "JOIN argos.synthetic_subjects s ON s.id = i.subject_id "
        "WHERE i.injected_confirmed_by IS NOT NULL AND i.reverted_by IS NULL"
    )
    args: tuple[Any, ...] = ()
    if campaign_id is not None:
        query += " AND s.campaign_id = %s"
        args = (campaign_id,)
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(query + " ORDER BY i.point", args).fetchall()
    return [
        {"id": row[0], "subject_id": row[1], "system_id": row[2], "point": row[3]} for row in rows
    ]
