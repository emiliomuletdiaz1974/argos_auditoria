"""Campaign seal (Plan Director §8.2, block 10).

Closing a campaign anchors in one hash **what was measured and against what**: every verdict, the
snapshot, the version of the ontology and the version of the library. Anyone can recompute it from
the tables and the journal; changing a single verdict breaks it.

Version 2 (security review F09-02, SEC-013 and SEC-016) also covers the plan (every unit, with its
resolved criterion and client parameters) and the approvals, and a seal is valid only when it is
the one and only `campaign.seal` anchor of its campaign. Campaigns sealed with version 1 verify with
version 1.

The Phase 07 evidence chain wraps this with a Merkle tree and a signature (ARG-066) without changing
what is sealed. A campaign is not sealed while a synthetic subject is still injected and not
reverted: what the client lent us goes back before we close (ADR-0008).
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import psycopg

from argos_challenges.store import CampaignStateError, campaign_record
from argos_challenges.synthetic import pending_reversions
from argos_common.errors import ArgosError
from argos_common.journal import canonicalize
from argos_common.journal_pg import PostgresJournal

JOURNAL_ACTION = "campaign.seal"
EVENT_SUBJECT = "argos.campaign.sealed"
EVENT_TYPE = "challenge.campaign_sealed.v1"
SEAL_SCHEMA = "argos/seal/2"
SYSTEM_ACTOR = "system:campaign"


class SealError(ArgosError):
    """The campaign cannot be sealed yet."""


def _digest(rows: list[Any]) -> str:
    text = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _plan_and_approvals(dsn: str, campaign_id: str) -> dict[str, str]:
    with psycopg.connect(dsn) as conn:
        units = conn.execute(
            "SELECT unit_id, unit FROM argos.campaign_units WHERE campaign_id = %s "
            "ORDER BY unit_id",
            (campaign_id,),
        ).fetchall()
        approvals = conn.execute(
            "SELECT gate, approved_by FROM argos.approvals WHERE campaign_id = %s "
            "ORDER BY gate, approved_by",
            (campaign_id,),
        ).fetchall()
    return {
        "units_sha256": _digest([[str(u), dict(body)] for u, body in units]),
        "approvals_sha256": _digest([[str(g), str(b)] for g, b in approvals]),
    }


def seal_payload(
    campaign: Mapping[str, Any],
    verdict_hashes: list[str],
    plan: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Exactly what the seal covers, in a canonical shape (without `plan`: version 1)."""
    payload: dict[str, Any] = {
        "campaign_id": str(campaign["id"]),
        "snapshot_hash": campaign.get("snapshot_hash"),
        "ontology_version": campaign.get("ontology_version"),
        "library_version": campaign.get("library_version"),
        "library_sha256": campaign.get("library_sha256"),
        "verdicts": sorted(verdict_hashes),
    }
    if plan is not None:
        payload = {"schema": SEAL_SCHEMA, **payload, **plan}
    return payload


def compute_seal(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonicalize(dict(payload)).encode("utf-8")).hexdigest()


def _verdict_hashes(dsn: str, campaign_id: str) -> list[str]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT verdict_hash FROM argos.verdicts WHERE campaign_id = %s ORDER BY verdict_hash",
            (campaign_id,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def seal_campaign(dsn: str, campaign_id: str) -> dict[str, Any]:
    """Close the campaign: compute the seal, store it and anchor it in the journal."""
    pending = pending_reversions(dsn, campaign_id)
    if pending:
        raise SealError(
            f"{len(pending)} synthetic injection(s) are not reverted: the campaign is not sealed"
        )
    campaign = campaign_record(dsn, campaign_id)
    if campaign["status"] == "sealed":
        raise CampaignStateError(f"the campaign {campaign_id} is already sealed")
    if campaign["status"] != "running":
        raise SealError(f"only a running campaign is sealed; {campaign_id} is {campaign['status']}")
    hashes = _verdict_hashes(dsn, campaign_id)
    payload = seal_payload(campaign, hashes, _plan_and_approvals(dsn, campaign_id))
    seal = compute_seal(payload)
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        updated = conn.execute(
            "UPDATE argos.campaigns SET status = 'sealed', seal = %s, sealed_at = %s "
            "WHERE id = %s AND status = 'running'",
            (seal, datetime.now(UTC), campaign_id),
        ).rowcount
        if updated != 1:  # another process sealed or failed it in between
            raise SealError(f"the campaign {campaign_id} stopped running before it was sealed")
        journal.append(
            SYSTEM_ACTOR,
            JOURNAL_ACTION,
            {"campaign": campaign_id, "seal": seal, "verdicts": len(hashes), "schema": SEAL_SCHEMA},
            conn=conn,
        )
    return {"campaign_id": campaign_id, "seal": seal, "verdicts": len(hashes)}


def verify_seal(dsn: str, campaign_id: str) -> bool:
    """Recompute the seal and check it is the one and only anchor of the campaign in the journal."""
    campaign = campaign_record(dsn, campaign_id)
    stored = campaign.get("seal")
    if not stored:
        return False
    # The anchors are looked up by their action (indexed) and payload, never by walking the
    # journal. More than one means the campaign was sealed twice: nothing to trust.
    with psycopg.connect(dsn) as conn:
        anchors = conn.execute(
            "SELECT payload->>'seal', payload->>'schema' FROM argos.audit_journal "
            "WHERE action = %s AND payload->>'campaign' = %s",
            (JOURNAL_ACTION, campaign_id),
        ).fetchall()
    if len(anchors) != 1 or anchors[0][0] != stored:
        return False
    plan = _plan_and_approvals(dsn, campaign_id) if anchors[0][1] == SEAL_SCHEMA else None
    recomputed = compute_seal(seal_payload(campaign, _verdict_hashes(dsn, campaign_id), plan))
    return bool(recomputed == stored)


async def announce_seal(bus: Any, sealed: Mapping[str, Any]) -> None:
    await bus.publish(EVENT_SUBJECT, EVENT_TYPE, dict(sealed))
