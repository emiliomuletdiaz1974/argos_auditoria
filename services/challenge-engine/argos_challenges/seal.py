"""Campaign seal (Plan Director §8.2, block 10).

Closing a campaign anchors in one hash **what was measured and against what**: every verdict, the
snapshot, the version of the ontology and the version of the library. Anyone can recompute it from
the tables and the journal; changing a single verdict breaks it.

The Phase 07 evidence chain wraps this with a Merkle tree and a signature (ARG-066) without changing
what is sealed. A campaign is not sealed while a synthetic subject is still injected and not
reverted: what the client lent us goes back before we close (ADR-0008).
"""

import hashlib
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
SYSTEM_ACTOR = "system:campaign"


class SealError(ArgosError):
    """The campaign cannot be sealed yet."""


def seal_payload(campaign: Mapping[str, Any], verdict_hashes: list[str]) -> dict[str, Any]:
    """Exactly what the seal covers, in a canonical shape."""
    return {
        "campaign_id": str(campaign["id"]),
        "snapshot_hash": campaign.get("snapshot_hash"),
        "ontology_version": campaign.get("ontology_version"),
        "library_version": campaign.get("library_version"),
        "library_sha256": campaign.get("library_sha256"),
        "verdicts": sorted(verdict_hashes),
    }


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
    hashes = _verdict_hashes(dsn, campaign_id)
    payload = seal_payload(campaign, hashes)
    seal = compute_seal(payload)
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE argos.campaigns SET status = 'sealed', seal = %s, sealed_at = %s WHERE id = %s",
            (seal, datetime.now(UTC), campaign_id),
        )
        journal.append(
            SYSTEM_ACTOR,
            JOURNAL_ACTION,
            {"campaign": campaign_id, "seal": seal, "verdicts": len(hashes)},
            conn=conn,
        )
    return {"campaign_id": campaign_id, "seal": seal, "verdicts": len(hashes)}


def verify_seal(dsn: str, campaign_id: str) -> bool:
    """Recompute the seal from the tables and check it is the one anchored in the journal."""
    campaign = campaign_record(dsn, campaign_id)
    stored = campaign.get("seal")
    if not stored:
        return False
    recomputed = compute_seal(seal_payload(campaign, _verdict_hashes(dsn, campaign_id)))
    if recomputed != stored:
        return False
    # The anchor is looked up by its action (indexed) and its payload, never by walking the
    # journal: every read of a campaign verifies its seal, and the journal only grows.
    with psycopg.connect(dsn) as conn:
        anchored = conn.execute(
            "SELECT 1 FROM argos.audit_journal "
            "WHERE action = %s AND payload->>'campaign' = %s AND payload->>'seal' = %s LIMIT 1",
            (JOURNAL_ACTION, campaign_id, stored),
        ).fetchone()
    return anchored is not None


async def announce_seal(bus: Any, sealed: Mapping[str, Any]) -> None:
    await bus.publish(EVENT_SUBJECT, EVENT_TYPE, dict(sealed))
