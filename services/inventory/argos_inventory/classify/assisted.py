"""Assisted classification: a model proposes, thresholds and the DPO dispose (ARG-025).

Until the local AI gateway exists (ARG-052, phase 6) the default model proposes nothing and the grey
zone stays unclassified and visible. Only columns without any CLASSIFIED_AS edge are sent, with
metadata only: a proposal never overrides a deterministic classification (deviation note
ARG-024-025, principle 7.2.1).
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from argos_common.journal_pg import PostgresJournal
from argos_inventory.graph.model import CATEGORIES
from argos_inventory.graph.store import GraphStore

ACCEPT = 0.85
REVIEW = 0.50
BATCH_SIZE = 20
MAX_SIBLINGS = 8
SYSTEM_PROMPT = (
    "You are the ARGOS data classifier. You receive database columns: name, type, table and "
    "sibling columns, never values. Assign each column exactly ONE category from this list: "
    + ", ".join(CATEGORIES)
    + '. Answer ONLY JSON: {"items": [{"key": "...", "category": "...", "confidence": 0.0, '
    '"reason": "fewer than 15 words"}]}'
)

_ALL_COLUMNS = (
    "MATCH (t:Table {system_id: $sid})-[:CONTAINS]->(c:Column) "
    "WHERE coalesce(c.missing, false) = false RETURN c.key, c.name, c.type, t.qualified_name"
)
_UNCLASSIFIED_KEYS = (
    "MATCH (t:Table {system_id: $sid})-[:CONTAINS]->(c:Column) "
    "WHERE NOT exists((c)-[:CLASSIFIED_AS]->()) AND coalesce(c.missing, false) = false "
    "RETURN c.key"
)
_AI_EDGE = (
    "MATCH (c:Column {key: $key}), (k:Category {name: $category}) "
    "MERGE (c)-[r:CLASSIFIED_AS]->(k) SET r.method = 'ai' SET r.confidence = $confidence "
    "SET r.prompt_hash = $prompt_hash SET r.at = $at"
)
_HUMAN_EDGE = (
    "MATCH (c:Column {key: $key}), (k:Category {name: $category}) "
    "MERGE (c)-[r:CLASSIFIED_AS]->(k) SET r.method = 'human' SET r.confidence = 1.0 "
    "SET r.reviewer = $reviewer SET r.at = $at"
)
_QUEUE_UPSERT = (
    "INSERT INTO argos.review_queue (node_key, system_id, qualified_name, proposed_category, "
    "confidence, reason, prompt_hash, proposed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (node_key) DO UPDATE SET proposed_category = EXCLUDED.proposed_category, "
    "confidence = EXCLUDED.confidence, reason = EXCLUDED.reason, "
    "prompt_hash = EXCLUDED.prompt_hash, proposed_at = EXCLUDED.proposed_at "
    "WHERE argos.review_queue.status = 'pending'"
)
_REVIEW_FOR_UPDATE = (
    "SELECT proposed_category, status FROM argos.review_queue WHERE node_key = %s FOR UPDATE"
)
_PENDING = (
    "SELECT node_key, system_id, qualified_name, proposed_category,"
    " confidence::float AS confidence, reason, status, proposed_at"
    " FROM argos.review_queue WHERE status = 'pending'"
    " AND (%(at)s::timestamptz IS NULL OR (proposed_at, node_key) < (%(at)s, %(key)s))"
    " ORDER BY proposed_at DESC, node_key DESC LIMIT %(limit)s"
)
_REVIEW_DECIDE = (
    "UPDATE argos.review_queue SET status = %s, decided_at = %s, decided_by = %s "
    "WHERE node_key = %s"
)


@dataclass(frozen=True, slots=True)
class ColumnContext:
    key: str
    name: str
    type: str
    table: str  # schema.table
    siblings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Proposal:
    key: str
    category: str
    confidence: float
    reason: str = ""


class ClassificationModel(Protocol):
    def propose(self, columns: Sequence[ColumnContext]) -> list[Proposal]: ...


class NullModel:
    """Default until ARG-052: proposes nothing, so the grey zone stays visible."""

    def propose(self, columns: Sequence[ColumnContext]) -> list[Proposal]:
        return []


@dataclass(frozen=True, slots=True)
class Triage:
    accepted: tuple[Proposal, ...]
    review: tuple[Proposal, ...]
    ignored: tuple[Proposal, ...]
    invalid: tuple[Proposal, ...]


@dataclass(frozen=True, slots=True)
class AssistedSummary:
    system_id: str
    sent: int
    accepted: int
    queued: int
    ignored: int
    invalid: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def prompt_hash(columns: Sequence[ColumnContext]) -> str:
    payload = json.dumps(
        [
            {
                "key": c.key,
                "name": c.name,
                "type": c.type,
                "table": c.table,
                "siblings": list(c.siblings),
            }
            for c in columns
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256((SYSTEM_PROMPT + payload).encode("utf-8")).hexdigest()[:16]


def triage(proposals: Sequence[Proposal], batch_keys: frozenset[str]) -> Triage:
    accepted: list[Proposal] = []
    review: list[Proposal] = []
    ignored: list[Proposal] = []
    invalid: list[Proposal] = []
    seen: set[str] = set()
    for proposal in proposals:
        valid = (
            proposal.key in batch_keys
            and proposal.key not in seen
            and proposal.category in CATEGORIES
            and 0.0 <= proposal.confidence <= 1.0
        )
        if not valid:
            invalid.append(proposal)
            continue
        seen.add(proposal.key)
        if proposal.confidence >= ACCEPT:
            accepted.append(proposal)
        elif proposal.confidence >= REVIEW:
            review.append(proposal)
        else:
            ignored.append(proposal)
    return Triage(tuple(accepted), tuple(review), tuple(ignored), tuple(invalid))


def grey_zone_columns(store: GraphStore, system_id: str) -> list[ColumnContext]:
    rows = store.query(_ALL_COLUMNS, {"sid": system_id}, ("key", "name", "type", "table"))
    unclassified = {
        str(r["key"]) for r in store.query(_UNCLASSIFIED_KEYS, {"sid": system_id}, ("key",))
    }
    names_by_table: dict[str, list[str]] = {}
    for row in rows:
        names_by_table.setdefault(str(row["table"]), []).append(str(row["name"]))
    columns = []
    for row in rows:
        if str(row["key"]) not in unclassified:
            continue
        table, name = str(row["table"]), str(row["name"])
        siblings = tuple(sorted(n for n in names_by_table[table] if n != name)[:MAX_SIBLINGS])
        columns.append(ColumnContext(str(row["key"]), name, str(row["type"]), table, siblings))
    return sorted(columns, key=lambda c: (c.table, c.name))


def classify_grey_zone(
    store: GraphStore,
    dsn: str,
    model: ClassificationModel,
    system_id: str,
    batch_size: int = BATCH_SIZE,
    now: Callable[[], datetime] = _utc_now,
) -> AssistedSummary:
    moment = now().astimezone(UTC)
    at = moment.isoformat()
    columns = grey_zone_columns(store, system_id)
    accepted = queued = ignored = invalid = 0
    for start in range(0, len(columns), batch_size):
        batch = columns[start : start + batch_size]
        by_key = {c.key: c for c in batch}
        result = triage(model.propose(batch), frozenset(by_key))
        batch_hash = prompt_hash(batch)
        for proposal in result.accepted:
            params = {
                "key": proposal.key,
                "category": proposal.category,
                "confidence": proposal.confidence,
                "prompt_hash": batch_hash,
                "at": at,
            }
            store.execute(_AI_EDGE, params)
        if result.review:
            with store.connection() as conn:
                for proposal in result.review:
                    column = by_key[proposal.key]
                    conn.execute(
                        _QUEUE_UPSERT,
                        (
                            proposal.key,
                            system_id,
                            f"{column.table}.{column.name}",
                            proposal.category,
                            proposal.confidence,
                            proposal.reason,
                            batch_hash,
                            moment,
                        ),
                    )
        accepted += len(result.accepted)
        queued += len(result.review)
        ignored += len(result.ignored)
        invalid += len(result.invalid)
    return AssistedSummary(system_id, len(columns), accepted, queued, ignored, invalid)


def decide_review(
    store: GraphStore,
    dsn: str,
    node_key: str,
    accepted: bool,
    reviewer: str,
    now: Callable[[], datetime] = _utc_now,
    corrected_to: str | None = None,
) -> str:
    """Accept or reject what the model proposed; rejecting may also say what the column is.

    A correction is a rejection for the calibration —the model was wrong, and that is the label it
    learns from— and a human classification with the category the person chose.
    """
    if not reviewer.startswith("user:"):
        raise ValueError("reviews are decided by a person: reviewer must be a user:<sub> actor")
    if corrected_to is not None and (accepted or corrected_to not in CATEGORIES):
        raise ValueError(
            f"a correction rejects the proposal and names a known category: {corrected_to!r}"
        )
    moment = now().astimezone(UTC)
    journal = PostgresJournal(dsn)
    with store.connection() as conn:
        row = conn.execute(_REVIEW_FOR_UPDATE, (node_key,)).fetchone()
        if row is None:
            raise LookupError(f"unknown review: {node_key}")
        category, current = str(row[0]), str(row[1])
        if current != "pending":
            raise ValueError(f"review already decided: {current}")
        status = "accepted" if accepted else "rejected"
        conn.execute(_REVIEW_DECIDE, (status, moment, reviewer, node_key))
        if accepted or corrected_to is not None:
            params = {
                "key": node_key,
                "category": category if accepted else corrected_to,
                "reviewer": reviewer,
                "at": moment.isoformat(),
            }
            store.execute(_HUMAN_EDGE, params, conn)
        payload = {"node_key": node_key, "category": category, "status": status}
        if corrected_to is not None:
            payload["corrected_to"] = corrected_to
        journal.append(reviewer, "inventory.review", payload, conn=conn)
    return status


def pending_reviews(
    dsn: str, limit: int, after: tuple[str, str] | None = None
) -> list[dict[str, Any]]:
    """What waits for a person, newest first. `id` and `created_at` are there for the cursor."""
    at, key = after if after else (None, None)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        rows = list(conn.execute(_PENDING, {"at": at, "key": key, "limit": limit}).fetchall())
    for row in rows:
        row["system_id"] = str(row["system_id"])
        row["proposed_at"] = row["proposed_at"].isoformat()
        row["id"] = row["node_key"]
        row["created_at"] = row["proposed_at"]
    return rows
