"""Immutable snapshots of the inventory graph: the dated photo a campaign runs against (ARG-023).

A snapshot is a relational projection of the live graph (nodes and their classifications) with a
content hash over its canonical form. Rows are frozen by trigger and the journal entry is written in
the same transaction, so a snapshot either exists with its entry or does not exist at all.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from argos_common.ids import uuid7
from argos_common.journal import canonicalize
from argos_common.journal_pg import PostgresJournal
from argos_inventory.graph.store import GraphStore

from .deltas import JOURNAL_ACTOR

_NODES = (
    "MATCH (n) WHERE n.key IS NOT NULL AND coalesce(n.missing, false) = false "
    "AND labels(n)[0] <> 'Category' "
    "RETURN n.key, labels(n)[0], n.name, n.qualified_name, n.system_id, n.status"
)
_CLASSIFICATIONS = (
    "MATCH (n)-[r:CLASSIFIED_AS]->(c:Category) RETURN n.key, c.name, r.method, r.confidence"
)
_INSERT_SNAPSHOT = (
    "INSERT INTO argos.inventory_snapshots (id, label, taken_at, node_count, content_hash) "
    "VALUES (%s, %s, %s, %s, %s)"
)
_INSERT_NODE = (
    "INSERT INTO argos.inventory_snapshot_nodes "
    "(snapshot_id, node_key, label, name, qualified_name, system_id, categories, status) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
)
# `status` completes what the campaign resolver needs from a snapshot (F05-11).
_FIELDS = ("node_key", "label", "name", "qualified_name", "system_id", "categories", "status")


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    id: str
    label: str
    taken_at: datetime
    node_count: int
    content_hash: str


def snapshot_hash(rows: list[dict[str, Any]]) -> str:
    # Journal v1 canonical form: a JSON object at the root and no floats (confidences are text).
    ordered = sorted(({k: row[k] for k in _FIELDS} for row in rows), key=lambda r: r["node_key"])
    return hashlib.sha256(canonicalize({"nodes": ordered}).encode("utf-8")).hexdigest()


def _confidence_text(value: Any) -> str | None:
    return None if value is None else f"{float(value):.4f}"


def _project(store: GraphStore) -> list[dict[str, Any]]:
    categories: dict[str, list[dict[str, Any]]] = {}
    classification_columns = ("key", "category", "method", "confidence")
    for row in store.query(_CLASSIFICATIONS, columns=classification_columns):
        categories.setdefault(str(row["key"]), []).append(
            {
                "category": row["category"],
                "method": row["method"],
                "confidence": _confidence_text(row["confidence"]),
            }
        )
    rows = []
    node_columns = ("key", "label", "name", "qualified_name", "system_id", "status")
    for row in store.query(_NODES, columns=node_columns):
        key = str(row["key"])
        rows.append(
            {
                "node_key": key,
                "label": row["label"],
                "name": row["name"],
                "qualified_name": row["qualified_name"],
                "system_id": row["system_id"],
                "categories": sorted(categories.get(key, []), key=lambda c: str(c["category"])),
                "status": row["status"],
            }
        )
    return rows


def take_snapshot(store: GraphStore, dsn: str, label: str) -> SnapshotRef:
    rows = _project(store)
    ref = SnapshotRef(str(uuid7()), label, datetime.now(UTC), len(rows), snapshot_hash(rows))
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            _INSERT_SNAPSHOT, (ref.id, ref.label, ref.taken_at, ref.node_count, ref.content_hash)
        )
        with conn.cursor() as cur:
            cur.executemany(
                _INSERT_NODE,
                [
                    (
                        ref.id,
                        r["node_key"],
                        r["label"],
                        r["name"],
                        r["qualified_name"],
                        r["system_id"],
                        Jsonb(r["categories"]),
                        r["status"],
                    )
                    for r in rows
                ],
            )
        payload = {
            "snapshot_id": ref.id,
            "label": label,
            "node_count": ref.node_count,
            "content_hash": ref.content_hash,
        }
        journal.append(JOURNAL_ACTOR, "inventory.snapshot", payload, conn=conn)
    return ref


def snapshot_nodes(dsn: str, snapshot_id: str) -> list[dict[str, Any]]:
    with psycopg.connect(dsn) as conn:
        cur = conn.execute(
            "SELECT node_key, label, name, qualified_name, system_id, categories, status "
            "FROM argos.inventory_snapshot_nodes WHERE snapshot_id = %s ORDER BY node_key",
            (snapshot_id,),
        )
        return [dict(zip(_FIELDS, row, strict=True)) for row in cur.fetchall()]


def verify_snapshot(dsn: str, snapshot_id: str) -> bool:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT content_hash, node_count FROM argos.inventory_snapshots WHERE id = %s",
            (snapshot_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"unknown snapshot: {snapshot_id}")
    nodes = snapshot_nodes(dsn, snapshot_id)
    return bool(row[0] == snapshot_hash(nodes) and row[1] == len(nodes))
