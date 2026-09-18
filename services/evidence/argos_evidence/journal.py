"""The journal anchored in each campaign (ARG-066, ADR-0002 and deviation note ARG-066).

There is no second journal verifier and no second hash formula here: the chain
is checked by ``PostgresJournal.verify``. This module adds what the chain alone
cannot give. The head of the journal (seq and entry hash) goes into the signed
object of the campaign root, and the signature and the time stamp fix it. After
that, even someone who rewrites the whole history and recomputes every hash is
caught: the entry at the anchored seq no longer has the anchored hash.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from argos_common.errors import ArgosError
from argos_common.journal import Anomaly
from argos_common.journal_pg import PostgresJournal
from argos_evidence.core.integrity import file_digest, seal_document
from argos_evidence.worm import WormAlreadyStoredError, WormStore

REPORT_SCHEMA = "argos/journal-report/1"


class JournalAnchorError(ArgosError):
    """The journal cannot be anchored, or its report cannot be written, as it stands."""


@dataclass(frozen=True)
class AnchorCheck:
    anchored_seq: int
    verified: int
    head_matches: bool
    anomalies: tuple[Anomaly, ...]

    @property
    def intact(self) -> bool:
        return self.head_matches and not self.anomalies


@dataclass(frozen=True)
class ReportRecord:
    key: str
    version_id: str
    sha256: str


def report_key(campaign_id: str) -> str:
    return f"campaigns/{campaign_id}/journal-report.json"


def anchor_head(dsn: str) -> dict[str, Any]:
    """The current head of the journal, after checking the whole chain up to it."""
    journal = PostgresJournal(dsn)
    seq, _ = journal.head()
    result = journal.verify(1, seq)
    if not result.intact:
        first = result.anomalies[0]
        raise JournalAnchorError(
            f"the journal is broken at entry {first.seq} ({first.reason}): it is not anchored"
        )
    return {"seq": result.head_seq, "entry_hash": result.head_hash.hex()}


def verify_anchor(dsn: str, head: Mapping[str, Any]) -> AnchorCheck:
    """Check the chain up to an anchored head and that its last entry is still that head."""
    seq = int(head["seq"])
    result = PostgresJournal(dsn).verify(1, seq)
    head_matches = result.head_seq == seq and result.head_hash.hex() == head["entry_hash"]
    return AnchorCheck(seq, result.verified, head_matches, result.anomalies)


def _report(campaign_id: str, head: Mapping[str, Any], check: AnchorCheck) -> bytes:
    return seal_document(
        {
            "schema": REPORT_SCHEMA,
            "kind": "journal_verification",
            "campaign_id": campaign_id,
            "anchored_head": {"seq": check.anchored_seq, "entry_hash": str(head["entry_hash"])},
            "verified_entries": check.verified,
            "head_matches": check.head_matches,
            "intact": check.intact,
            "anomalies": [{"seq": a.seq, "reason": a.reason} for a in check.anomalies],
        }
    )


def journal_report(
    dsn: str,
    store: WormStore,
    campaign_id: str,
    head: Mapping[str, Any],
    retain_until: dt.datetime,
) -> ReportRecord:
    """Write, once, the verification report of the journal up to the campaign's anchored head.

    The report has no time in it, so the same journal and head always give the same bytes: a
    retry finds the stored report and checks it byte for byte.
    """
    body = _report(campaign_id, head, verify_anchor(dsn, head))
    key = report_key(campaign_id)
    try:
        stored = store.put_immutable(key, body, retain_until)
        return ReportRecord(key, stored.version_id, stored.sha256)
    except WormAlreadyStoredError:
        version_id = store.version_of(key)
        if store.get(key, version_id) != body:
            raise JournalAnchorError(
                f"{key} was written from another state of the journal"
            ) from None
        return ReportRecord(key, version_id, file_digest(body))
