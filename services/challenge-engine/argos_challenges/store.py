"""Reading and writing of campaigns, units, verdicts and approvals (ARG-043, ARG-046, ARG-047).

This is the only module that writes `argos.verdicts`, and the architecture test of F05-04 keeps it
that way. Every write goes with its journal entry in the same transaction, and a verdict is written
once per unit: an activity that retries after a crash finds the verdict already there and returns it
instead of emitting a second one.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from argos_challenges.evaluator import Verdict
from argos_common.errors import ArgosError
from argos_common.ids import uuid7
from argos_common.journal_pg import PostgresJournal

STATUSES = ("planned", "pinned", "running", "sealed", "failed")
# Which status can follow which: a campaign never goes back.
TRANSITIONS: Mapping[str, frozenset[str]] = {
    "planned": frozenset({"pinned", "failed"}),
    "pinned": frozenset({"running", "failed"}),
    "running": frozenset({"sealed", "failed"}),
    "sealed": frozenset(),
    "failed": frozenset(),
}
JOURNAL_ACTOR = "system:campaign"
DEFAULT_APPROVALS = 1
# Gates two different people must approve (ARG-047): sampling decides what is not looked at.
DOUBLE_CONTROL_GATES = frozenset({"sampling"})
START_GATE = "start"
APPROVAL_SUBJECT = "argos.campaign.approval_requested"
APPROVAL_EVENT_TYPE = "challenge.approval_requested.v1"

_INSERT_VERDICT = (
    "INSERT INTO argos.verdicts (id, campaign_id, unit_id, challenge_id, challenge_version, "
    "obligation, system_id, node_key, result, verdict, verdict_hash, probe_journal_seq) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (campaign_id, unit_id) DO NOTHING RETURNING id::text"
)


class CampaignStateError(ArgosError):
    """The campaign, the gate or the verdict was used out of its state."""


def create_campaign(dsn: str, name: str, scope: Mapping[str, Any], created_by: str) -> str:
    if not created_by.startswith("user:"):
        raise CampaignStateError("a campaign is created by a person: user:<sub>")
    campaign_id = str(uuid7())
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.campaigns (id, name, scope, created_by) VALUES (%s, %s, %s, %s)",
            (campaign_id, name, Jsonb(dict(scope)), created_by),
        )
        journal.append(
            created_by, "campaign.create", {"campaign": campaign_id, "name": name}, conn=conn
        )
    return campaign_id


def pin_campaign(
    dsn: str,
    campaign_id: str,
    *,
    snapshot_id: str | None,
    snapshot_hash: str | None,
    ontology_version: str,
    library_version: str,
    library_sha256: str,
    applicability_run: str | None,
) -> None:
    """Fix what the campaign measures against. Only once: a pinned campaign is reproducible."""
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        updated = conn.execute(
            "UPDATE argos.campaigns SET status = 'pinned', snapshot_id = %s, snapshot_hash = %s, "
            "ontology_version = %s, library_version = %s, library_sha256 = %s, "
            "applicability_run = %s WHERE id = %s AND status = 'planned'",
            (
                snapshot_id,
                snapshot_hash,
                ontology_version,
                library_version,
                library_sha256,
                applicability_run,
                campaign_id,
            ),
        ).rowcount
        if not updated:
            raise CampaignStateError(f"the campaign {campaign_id} is not planned, or is pinned")
        journal.append(
            JOURNAL_ACTOR,
            "campaign.pin",
            {
                "campaign": campaign_id,
                "snapshot": snapshot_id,
                "snapshot_hash": snapshot_hash,
                "ontology": ontology_version,
                "library": library_version,
            },
            conn=conn,
        )


def save_units(dsn: str, campaign_id: str, units: Sequence[Mapping[str, Any]]) -> int:
    """Store the compiled units. Re-compiling the same campaign leaves them as they are."""
    if not units:
        return 0
    rows = [(campaign_id, str(unit["unit_id"]), Jsonb(dict(unit))) for unit in units]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO argos.campaign_units (campaign_id, unit_id, unit) VALUES (%s, %s, %s) "
            "ON CONFLICT (campaign_id, unit_id) DO NOTHING",
            rows,
        )
    return len(rows)


def persist_verdict(
    dsn: str,
    campaign_id: str,
    unit: Mapping[str, Any],
    verdict: Verdict,
    probe_journal_seq: int | None = None,
) -> tuple[str, bool]:
    """Write the verdict of a unit. Returns its id and whether this call created it."""
    verdict_id = str(uuid7())
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            _INSERT_VERDICT,
            (
                verdict_id,
                campaign_id,
                verdict.unit_id,
                verdict.challenge_id,
                verdict.challenge_version,
                str(unit["obligation"]),
                str(unit["system_id"]),
                verdict.node_key,
                verdict.result,
                Jsonb(verdict.as_dict()),
                verdict.hash,
                probe_journal_seq,
            ),
        ).fetchone()
        if row is None:
            existing = conn.execute(
                "SELECT id::text FROM argos.verdicts WHERE campaign_id = %s AND unit_id = %s",
                (campaign_id, verdict.unit_id),
            ).fetchone()
            if existing is None:  # pragma: no cover - only if someone deleted it, which is barred
                raise CampaignStateError("the verdict disappeared between write and read")
            return str(existing[0]), False
        conn.execute(
            "UPDATE argos.campaign_units SET status = 'done' "
            "WHERE campaign_id = %s AND unit_id = %s",
            (campaign_id, verdict.unit_id),
        )
        journal.append(
            "system:evaluator",
            "verdict.emit",
            {
                "campaign": campaign_id,
                "verdict": verdict_id,
                "unit": verdict.unit_id,
                "result": verdict.result,
                "verdict_hash": verdict.hash,
            },
            conn=conn,
        )
    return verdict_id, True


def request_approval(dsn: str, campaign_id: str, gate: str, payload: Mapping[str, Any]) -> bool:
    """Open a gate. Asking twice keeps the first request: what was approved does not change.

    Returns whether this call opened it, so the announcement goes out once.
    """
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        created = conn.execute(
            "INSERT INTO argos.approval_requests (campaign_id, gate, payload) "
            "VALUES (%s, %s, %s) ON CONFLICT (campaign_id, gate) DO NOTHING",
            (campaign_id, gate, Jsonb(dict(payload))),
        ).rowcount
        if created:
            journal.append(
                JOURNAL_ACTOR,
                "approval.request",
                {"campaign": campaign_id, "gate": gate, "payload": dict(payload)},
                conn=conn,
            )
    return bool(created)


def grant_approval(
    dsn: str, campaign_id: str, gate: str, approver: str, needed: int = DEFAULT_APPROVALS
) -> tuple[int, bool]:
    """Record one approval. Returns how many there are and whether the gate opens."""
    if not approver.startswith("user:"):
        raise CampaignStateError("a gate is approved by a person: user:<sub>")
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        request = conn.execute(
            "SELECT payload::text FROM argos.approval_requests "
            "WHERE campaign_id = %s AND gate = %s",
            (campaign_id, gate),
        ).fetchone()
        if request is None:
            raise CampaignStateError(f"the gate {gate} was not requested")
        already = conn.execute(
            "SELECT 1 FROM argos.approvals "
            "WHERE campaign_id = %s AND gate = %s AND approved_by = %s",
            (campaign_id, gate, approver),
        ).fetchone()
        if already is not None:
            raise CampaignStateError(f"the gate {gate} was already approved by {approver}")
        conn.execute(
            "INSERT INTO argos.approvals (campaign_id, gate, approved_by) VALUES (%s, %s, %s)",
            (campaign_id, gate, approver),
        )
        count = conn.execute(
            "SELECT count(*) FROM argos.approvals WHERE campaign_id = %s AND gate = %s",
            (campaign_id, gate),
        ).fetchone()
        granted = 0 if count is None else int(count[0])
        journal.append(
            approver,
            "approval.grant",
            {
                "campaign": campaign_id,
                "gate": gate,
                "approvals": granted,
                "needed": needed,
                "approved": request[0],
            },
            conn=conn,
        )
    return granted, granted >= needed


def approvals_needed(gate: str) -> int:
    return 2 if gate in DOUBLE_CONTROL_GATES else DEFAULT_APPROVALS


def gate_is_open(dsn: str, campaign_id: str, gate: str) -> bool:
    """What opens a gate is the approvals people recorded, not the signal that announces them."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT count(DISTINCT approved_by) FROM argos.approvals "
            "WHERE campaign_id = %s AND gate = %s AND approved_by LIKE 'user:%%'",
            (campaign_id, gate),
        ).fetchone()
    return row is not None and int(row[0]) >= approvals_needed(gate)


def set_status(dsn: str, campaign_id: str, status: str) -> None:
    if status not in STATUSES:
        raise CampaignStateError(f"unknown campaign status: {status!r}")
    with psycopg.connect(dsn) as conn:
        current = conn.execute(
            "SELECT status FROM argos.campaigns WHERE id = %s", (campaign_id,)
        ).fetchone()
        if current is None:
            raise CampaignStateError(f"unknown campaign: {campaign_id}")
        if status not in TRANSITIONS[str(current[0])]:
            raise CampaignStateError(f"illegal status change {current[0]} -> {status}")
        conn.execute("UPDATE argos.campaigns SET status = %s WHERE id = %s", (status, campaign_id))


def campaign_record(dsn: str, campaign_id: str) -> dict[str, Any]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT name, scope, status, snapshot_id::text, snapshot_hash, ontology_version, "
            "library_version, library_sha256, applicability_run::text, created_by, seal, "
            "(SELECT count(*) FROM argos.campaign_units u WHERE u.campaign_id = c.id) "
            "FROM argos.campaigns c WHERE id = %s",
            (campaign_id,),
        ).fetchone()
    if row is None:
        raise CampaignStateError(f"unknown campaign: {campaign_id}")
    fields = (
        "name",
        "scope",
        "status",
        "snapshot_id",
        "snapshot_hash",
        "ontology_version",
        "library_version",
        "library_sha256",
        "applicability_run",
        "created_by",
        "seal",
        "units",
    )
    record = dict(zip(fields, row, strict=True))
    record["id"] = campaign_id
    return record


_CAMPAIGNS = (
    "SELECT id::text, name, status, created_by, created_at, sealed_at FROM argos.campaigns"
    " WHERE (%(at)s::timestamptz IS NULL OR (created_at, id::text) < (%(at)s, %(id)s))"
    " ORDER BY created_at DESC, id DESC LIMIT %(limit)s"
)
_GATES = (
    "SELECT r.gate, r.payload, r.requested_at, count(a.approved_by),"
    " coalesce(array_agg(a.approved_by ORDER BY a.approved_at) FILTER"
    " (WHERE a.approved_by IS NOT NULL), '{}') FROM argos.approval_requests r"
    " LEFT JOIN argos.approvals a ON a.campaign_id = r.campaign_id AND a.gate = r.gate"
    " WHERE r.campaign_id = %s GROUP BY r.gate, r.payload, r.requested_at ORDER BY r.requested_at"
)


_VERDICTS = (
    "SELECT id::text, unit_id, challenge_id, challenge_version, obligation, system_id::text,"
    " node_key, result, verdict_hash, created_at FROM argos.verdicts"
    " WHERE campaign_id = %(campaign)s"
    " AND (%(at)s::timestamptz IS NULL OR (created_at, id::text) > (%(at)s, %(id)s))"
    " ORDER BY created_at, id LIMIT %(limit)s"
)


def list_verdicts(
    dsn: str, campaign_id: str, limit: int, after: tuple[str, str] | None = None
) -> list[dict[str, Any]]:
    """The verdicts of a campaign, in the order they were written, for a page at a time."""
    at, ident = after if after else (None, None)
    params = {"campaign": campaign_id, "at": at, "id": ident, "limit": limit}
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(_VERDICTS, params).fetchall()
    fields = (
        "id",
        "unit_id",
        "challenge_id",
        "challenge_version",
        "obligation",
        "system_id",
        "node_key",
        "result",
        "verdict_hash",
    )
    return [
        {**dict(zip(fields, row[:-1], strict=True)), "created_at": row[-1].isoformat()}
        for row in rows
    ]


def running_campaigns(dsn: str) -> list[str]:
    """The campaigns a signal can still reach: the ones Temporal is running right now."""
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT id::text FROM argos.campaigns WHERE status = 'running' ORDER BY created_at"
        ).fetchall()
    return [str(row[0]) for row in rows]


def list_campaigns(
    dsn: str, limit: int, after: tuple[str, str] | None = None
) -> list[dict[str, Any]]:
    """The campaigns, newest first, in keyset order so a page never repeats one."""
    at, ident = after if after else (None, None)
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(_CAMPAIGNS, {"at": at, "id": ident, "limit": limit}).fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "status": row[2],
            "created_by": row[3],
            "created_at": row[4].isoformat(),
            "sealed_at": row[5].isoformat() if row[5] else None,
        }
        for row in rows
    ]


def campaign_gates(dsn: str, campaign_id: str) -> list[dict[str, Any]]:
    """The gates the campaign asked for, in the order it asked, and their approvals."""
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(_GATES, (campaign_id,)).fetchall()
    return [
        {
            "gate": str(row[0]),
            "payload": row[1],
            "requested_at": row[2].isoformat(),
            "approvals": int(row[3]),
            "approved_by": list(row[4]),
            "needed": approvals_needed(str(row[0])),
        }
        for row in rows
    ]


def campaign_plan(dsn: str, campaign_id: str) -> dict[str, Any] | None:
    """What the campaign is going to ask, literally, before it asks anything.

    It exists from the moment the campaign is prepared —pinned, compiled and waiting at the start
    gate— and until then there is nothing honest to show: None. What cannot be verified is not
    hidden among the units, it has its own section.
    """
    campaign_record(dsn, campaign_id)  # an unknown campaign is an error, not an empty plan
    with psycopg.connect(dsn) as conn:
        start = conn.execute(
            "SELECT payload FROM argos.approval_requests WHERE campaign_id = %s AND gate = %s",
            (campaign_id, START_GATE),
        ).fetchone()
        if start is None:
            return None
        units = conn.execute(
            "SELECT unit, status FROM argos.campaign_units WHERE campaign_id = %s ORDER BY unit_id",
            (campaign_id,),
        ).fetchall()
    payload = dict(start[0])
    return {
        "campaign_id": campaign_id,
        "units": [dict(row[0]) for row in units],
        "unverifiable": list(payload.get("unverifiable", [])),
        "probes_run": sum(1 for row in units if row[1] != "pending"),
    }


async def announce_approval(bus: Any, campaign_id: str, gate: str) -> None:
    """Tell whoever listens that a gate awaits a person: the ITSM of the client, for one."""
    await bus.publish(
        APPROVAL_SUBJECT,
        APPROVAL_EVENT_TYPE,
        {"campaign_id": campaign_id, "gate": gate, "approvals_needed": approvals_needed(gate)},
    )
