"""Life cycle of a finding (ARG-048).

A finding is a non-conformity with an owner, a severity and a way out: `open` → `in_remediation` →
`pending_verification` → `closed_compliant`, or `reopened` when the re-run does not confirm it. The
exceptional way is `risk_accepted`, a documented decision with an expiry, because refusing that way
only produces findings that stay open forever and nobody looks at.

Two rules keep the count honest:
- **deduplication by fingerprint** (challenge and node): successive campaigns do not multiply a
  finding, they raise its counter, and from three different campaigns they raise its severity;
- **a reopening is not a recurrence**: the problem is the same one, seen again.
"""

import hashlib
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from argos_challenges.evaluator import Verdict
from argos_common.errors import ArgosError
from argos_common.ids import uuid7
from argos_common.journal_pg import PostgresJournal

STATUSES = (
    "open",
    "in_remediation",
    "pending_verification",
    "closed_compliant",
    "reopened",
    "risk_accepted",
)
TRANSITIONS: Mapping[str, frozenset[str]] = {
    "open": frozenset({"in_remediation", "risk_accepted"}),
    "in_remediation": frozenset({"pending_verification", "risk_accepted"}),
    "pending_verification": frozenset({"closed_compliant", "reopened"}),
    "reopened": frozenset({"in_remediation", "risk_accepted"}),
    "risk_accepted": frozenset({"reopened"}),  # when the acceptance expires
    "closed_compliant": frozenset(),
}
SEVERITIES = ("low", "medium", "high", "critical")
ESCALATION_CAMPAIGNS = 3
EVENT_SUBJECT = "argos.challenge.finding_opened"
EVENT_TYPE = "challenge.finding_opened.v1"
SYSTEM_ACTOR = "system:findings"

_OPEN_OR_RECUR = """
INSERT INTO argos.findings
  (id, fingerprint, campaign_id, challenge_id, obligation, system_id, node_key, severity,
   campaigns_seen, last_verdict, detail)
VALUES (%(id)s, %(fingerprint)s, %(campaign_id)s, %(challenge_id)s, %(obligation)s, %(system_id)s,
        %(node_key)s, %(severity)s, ARRAY[%(campaign_text)s], %(verdict_id)s, %(detail)s)
ON CONFLICT (fingerprint) DO UPDATE SET
  occurrences = argos.findings.occurrences
                + (CASE WHEN %(counts)s AND NOT argos.findings.campaigns_seen
                             @> ARRAY[%(campaign_text)s] THEN 1 ELSE 0 END),
  campaigns_seen = CASE WHEN %(counts)s AND NOT argos.findings.campaigns_seen
                             @> ARRAY[%(campaign_text)s]
                        THEN argos.findings.campaigns_seen || ARRAY[%(campaign_text)s]
                        ELSE argos.findings.campaigns_seen END,
  status = CASE WHEN argos.findings.status = 'closed_compliant' THEN 'reopened'
                ELSE argos.findings.status END,
  last_verdict = %(verdict_id)s,
  detail = %(detail)s,
  updated_at = now()
RETURNING id::text, occurrences, severity, status, (xmax = 0) AS created
"""


class FindingError(ArgosError):
    """The finding was moved out of its life cycle."""


def fingerprint(challenge_id: str, node_key: str) -> str:
    return hashlib.sha256(f"{challenge_id}|{node_key}".encode()).hexdigest()


def escalate(severity: str, occurrences: int) -> str:
    """From three campaigns, one level up; `critical` does not escalate any further."""
    if occurrences < ESCALATION_CAMPAIGNS:
        return severity
    index = SEVERITIES.index(severity)
    return SEVERITIES[min(index + 1, len(SEVERITIES) - 1)]


def open_or_recur(
    dsn: str,
    campaign_id: str,
    unit: Mapping[str, Any],
    verdict: Verdict,
    verdict_id: str,
    counts_as_recurrence: bool = True,
) -> dict[str, Any]:
    """Open the finding of a non-compliant verdict, or record that it is here again.

    A remediation run does not count: it is the same problem being verified, not a new sighting.
    """
    mark = fingerprint(str(unit["challenge_id"]), str(unit["node_key"]))
    parameters = {
        "id": str(uuid7()),
        "fingerprint": mark,
        "campaign_id": campaign_id,
        "campaign_text": campaign_id,
        "challenge_id": str(unit["challenge_id"]),
        "obligation": str(unit["obligation"]),
        "system_id": str(unit["system_id"]),
        "node_key": str(unit["node_key"]),
        "severity": str(unit["severity"]),
        "verdict_id": verdict_id,
        "detail": Jsonb(verdict.detail),
        "counts": counts_as_recurrence,
    }
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        row = conn.execute(_OPEN_OR_RECUR, parameters).fetchone()
        if row is None:  # pragma: no cover - the upsert always returns its row
            raise FindingError("the finding could not be written")
        finding_id, occurrences, severity, status, created = row
        raised = escalate(str(severity), int(occurrences))
        if raised != severity:
            conn.execute(
                "UPDATE argos.findings SET severity = %s, updated_at = now() WHERE id = %s",
                (raised, finding_id),
            )
        action = "finding.open" if created else "finding.recur"
        journal.append(
            SYSTEM_ACTOR,
            action,
            {
                "finding": str(finding_id),
                "fingerprint": mark,
                "campaign": campaign_id,
                "occurrences": int(occurrences),
                "severity": raised,
            },
            conn=conn,
        )
    return {
        "id": str(finding_id),
        "created": bool(created),
        "occurrences": int(occurrences),
        "severity": raised,
        "status": str(status),
    }


async def announce(bus: Any, finding: Mapping[str, Any], campaign_id: str) -> None:
    """Tell the world a finding is open; the consola and the webhooks listen (ARG-079)."""
    await bus.publish(
        EVENT_SUBJECT,
        EVENT_TYPE,
        {
            "finding_id": str(finding["id"]),
            "campaign_id": campaign_id,
            "severity": str(finding["severity"]),
            "occurrences": int(finding["occurrences"]),
        },
    )


def transition(
    dsn: str,
    finding_id: str,
    to: str,
    actor: str,
    note: str = "",
    risk_expiry: date | None = None,
) -> str:
    """Move a finding, with the closed state machine and its journal entry."""
    if to not in STATUSES:
        raise FindingError(f"unknown status: {to!r}")
    if not actor.startswith(("user:", "system:")):
        raise FindingError("a transition has an actor: user:<sub> or system:<name>")
    if to == "risk_accepted" and (not note.strip() or risk_expiry is None):
        raise FindingError("accepting a risk needs a justification and an expiry date")
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT status FROM argos.findings WHERE id = %s FOR UPDATE", (finding_id,)
        ).fetchone()
        if row is None:
            raise FindingError(f"unknown finding: {finding_id}")
        current = str(row[0])
        if to not in TRANSITIONS[current]:
            raise FindingError(f"illegal transition {current} -> {to}")
        conn.execute(
            "UPDATE argos.findings SET status = %s, risk_note = %s, risk_expiry = %s, "
            "updated_at = now() WHERE id = %s",
            (to, note or None, risk_expiry, finding_id),
        )
        journal.append(
            actor,
            "finding.transition",
            {"finding": finding_id, "from": current, "to": to},
            conn=conn,
        )
    return current


def expire_risk_acceptances(dsn: str, today: date | None = None) -> list[str]:
    """An acceptance that expired comes back as reopened, with its entry in the journal."""
    moment = today or datetime.now(UTC).date()
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT id::text FROM argos.findings "
            "WHERE status = 'risk_accepted' AND risk_expiry < %s ORDER BY id",
            (moment,),
        ).fetchall()
    expired = [str(row[0]) for row in rows]
    for finding_id in expired:
        transition(dsn, finding_id, "reopened", SYSTEM_ACTOR)
    return expired
