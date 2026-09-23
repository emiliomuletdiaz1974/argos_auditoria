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
# What only a re-run of the challenge decides (ARG-049): a person does not close a finding, nor
# reopen one; the verification, or an expired acceptance, does.
VERIFICATION_ONLY = frozenset({"closed_compliant", "reopened"})
SEVERITIES = ("low", "medium", "high", "critical")
SEVERITY_RANK = {severity: rank for rank, severity in enumerate(SEVERITIES, start=1)}
ESCALATION_CAMPAIGNS = 3
EVENT_SUBJECT = "argos.challenge.finding_opened"
EVENT_TYPE = "challenge.finding_opened.v1"
SYSTEM_ACTOR = "system:findings"
REMEDIATION_ACTOR = "system:remediation"

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


# A risk is accepted for a while, never for ever: the finding comes back when it expires (SEC-042).
RISK_ACCEPTANCE_MAX_DAYS = 365


def check_risk_expiry(expiry: date, today: date | None = None) -> None:
    today = today or date.today()
    if expiry <= today:
        raise FindingError("a risk is accepted until a future date")
    if (expiry - today).days > RISK_ACCEPTANCE_MAX_DAYS:
        raise FindingError(
            f"a risk is accepted for {RISK_ACCEPTANCE_MAX_DAYS} days at most, then reviewed again"
        )


def check_request(to: str, actor: str, note: str = "", risk_expiry: date | None = None) -> None:
    """The rules of a transition that do not depend on the current status."""
    if to not in STATUSES:
        raise FindingError(f"unknown status: {to!r}")
    if not actor.startswith(("user:", "system:")):
        raise FindingError("a transition has an actor: user:<sub> or system:<name>")
    if to in VERIFICATION_ONLY and actor.startswith("user:"):
        raise FindingError(
            f"a person does not move a finding to {to}: only a re-run of its challenge does"
        )
    if to == "closed_compliant" and actor != REMEDIATION_ACTOR:
        # Closing is the verdict of the re-run of the stored WorkUnit, never a person's say-so.
        raise FindingError(f"only {REMEDIATION_ACTOR} closes a finding as compliant")
    if to == "risk_accepted" and (not note.strip() or risk_expiry is None):
        raise FindingError("accepting a risk needs a justification and an expiry date")
    if to == "risk_accepted" and risk_expiry is not None:
        check_risk_expiry(risk_expiry)


def transition(
    dsn: str,
    finding_id: str,
    to: str,
    actor: str,
    note: str = "",
    risk_expiry: date | None = None,
) -> str:
    """Move a finding, with the closed state machine and its journal entry."""
    check_request(to, actor, note, risk_expiry)
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


def person_transitions(status: str) -> list[str]:
    """Where a person may move a finding from `status`; the rest belongs to the re-run."""
    return sorted(TRANSITIONS[status] - VERIFICATION_ONLY)


# Worst first as text, so a cursor can point at a place in the order. Written out in full, and a
# pure test keeps it in step with SEVERITY_RANK.
ORDER_KEY_SQL = (
    "(CASE f.severity WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 "
    "WHEN 'critical' THEN 4 END)::text || '-' || lpad(f.occurrences::text, 6, '0')"
)
_LIST = (
    "SELECT f.id::text, f.challenge_id, f.obligation, f.system_id::text, f.node_key, f.severity,"
    " f.status, f.occurrences, f.campaign_id::text, f.risk_expiry, f.updated_at,"
    " (CASE f.severity WHEN 'low' THEN 1 WHEN 'medium' THEN 2 WHEN 'high' THEN 3 "
    "WHEN 'critical' THEN 4 END)::text || '-' || lpad(f.occurrences::text, 6, '0') AS order_key"
    " FROM argos.findings f"
    " WHERE (%(status)s::text IS NULL OR f.status = %(status)s)"
    " AND (%(severity)s::text IS NULL OR f.severity = %(severity)s)"
    " AND (%(campaign)s::uuid IS NULL OR f.campaign_id = %(campaign)s::uuid)"
    " AND (%(key)s::text IS NULL OR ((CASE f.severity WHEN 'low' THEN 1 WHEN 'medium' THEN 2 "
    "WHEN 'high' THEN 3 WHEN 'critical' THEN 4 END)::text || '-' || "
    "lpad(f.occurrences::text, 6, '0'), f.id::text) < (%(key)s, %(id)s))"
    " ORDER BY order_key DESC, f.id DESC LIMIT %(limit)s"
)
_DETAIL = (
    "SELECT id::text, fingerprint, campaign_id::text, challenge_id, obligation, system_id::text,"
    " node_key, severity, status, occurrences, campaigns_seen, detail, risk_note, risk_expiry,"
    " created_at, updated_at, last_verdict::text FROM argos.findings WHERE id = %s"
)
# A read of the verdict, on its own: the boundary test of F05-04 looks for write keywords next to
# the verdict table, and a finding's own columns (its `updated_at`) have no business there.
_VERDICT = (
    "SELECT v.id::text, v.result, v.verdict, v.verdict_hash, v.challenge_version,"
    " v.probe_journal_seq, v.created_at, j.action, j.at_canon FROM argos.verdicts v"
    " LEFT JOIN argos.audit_journal j ON j.seq = v.probe_journal_seq WHERE v.id = %s"
)


def list_findings(
    dsn: str,
    limit: int,
    after: tuple[str, str] | None = None,
    *,
    status: str | None = None,
    severity: str | None = None,
    campaign_id: str | None = None,
) -> list[dict[str, Any]]:
    """The findings, worst first: severity, then how often they came back, then id.

    `order_key` carries that order as text so a cursor can point at a place in it.
    """
    key, ident = after if after else (None, None)
    params = {
        "status": status,
        "severity": severity,
        "campaign": campaign_id,
        "key": key,
        "id": ident,
        "limit": limit,
    }
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(_LIST, params).fetchall()
    return [
        {
            "id": row[0],
            "challenge_id": row[1],
            "obligation": row[2],
            "system_id": row[3],
            "node_key": row[4],
            "severity": row[5],
            "severity_rank": SEVERITY_RANK[str(row[5])],
            "status": row[6],
            "occurrences": int(row[7]),
            "campaign_id": row[8],
            "risk_expiry": row[9].isoformat() if row[9] else None,
            "updated_at": row[10].isoformat(),
            "order_key": row[11],
        }
        for row in rows
    ]


_HISTORY = (
    "SELECT seq, at, actor, action, payload FROM argos.audit_journal"
    " WHERE action IN ('finding.open', 'finding.recur', 'finding.transition')"
    " AND payload->>'finding' = %s ORDER BY seq"
)


def _history_step(row: tuple[Any, ...]) -> dict[str, Any]:
    seq, at, actor, action, payload = row
    to = {"finding.open": "open", "finding.transition": payload.get("to")}.get(action)
    return {
        "seq": int(seq),
        "at": at.isoformat(),
        "actor": actor,
        "action": action,
        "from": payload.get("from"),
        "to": to,
        "occurrences": payload.get("occurrences"),
    }


def finding_detail(dsn: str, finding_id: str) -> dict[str, Any] | None:
    """A finding with the verdict that opened it, the question asked and its journal history."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(_DETAIL, (finding_id,)).fetchone()
        seen = (
            conn.execute(_VERDICT, (row[16],)).fetchone()
            if row is not None and row[16] is not None
            else None
        )
        history = conn.execute(_HISTORY, (finding_id,)).fetchall() if row is not None else []
    if row is None:
        return None
    verdict = None
    if seen is not None:
        probe = (
            {"seq": int(seen[5]), "action": seen[7], "at": seen[8]} if seen[5] is not None else None
        )
        verdict = {
            "id": seen[0],
            "result": seen[1],
            "verdict": seen[2],
            "verdict_hash": seen[3],
            "challenge_version": seen[4],
            "sampling": ((seen[2] or {}).get("detail") or {}).get("sampling"),
            "probe_journal": probe,
            "created_at": seen[6].isoformat(),
        }
    return {
        "id": row[0],
        "fingerprint": row[1],
        "campaign_id": row[2],
        "challenge_id": row[3],
        "obligation": row[4],
        "system_id": row[5],
        "node_key": row[6],
        "severity": row[7],
        "status": row[8],
        "occurrences": int(row[9]),
        "campaigns_seen": list(row[10]),
        "detail": row[11],
        "risk_note": row[12],
        "risk_expiry": row[13].isoformat() if row[13] else None,
        "created_at": row[14].isoformat(),
        "updated_at": row[15].isoformat(),
        "verdict": verdict,
        "allowed_transitions": person_transitions(str(row[8])),
        "history": [_history_step(step) for step in history],
    }
