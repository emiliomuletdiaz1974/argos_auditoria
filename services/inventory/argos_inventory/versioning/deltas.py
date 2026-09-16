"""Inventory deltas between scan runs: appeared, disappeared and anomalous growth (ARG-023).

Disappearances are marked, never deleted: in an evidence product deleting inventory destroys
context. The first completed run of a system is the baseline and produces no deltas.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from argos_common.journal_pg import PostgresJournal
from argos_inventory.discovery.events import EventPublisher
from argos_inventory.graph.store import GraphStore

GROWTH_FACTOR = 3.0
GROWTH_MIN_ROWS = 1000
DELTA_KINDS = ("appeared", "disappeared", "anomalous_growth")
JOURNAL_ACTOR = "system:inventory"

# Labels a System reaches through CONTAINS; every one stores system_id. The deltas ask per label
# with an indexed property map instead of walking CONTAINS*1..3 from the System, which AGE 1.5.0
# plans as a scan of the whole graph (1.5 s per system with 10 200 columns; task F03-15).
CONTAINED_LABELS = ("Schema", "Table", "Column", "FileArea")
APPEARED_BY_LABEL = {
    label: (
        f"MATCH (n:{label} {{system_id: $sid}}) WHERE n.first_seen >= $t0 "
        "RETURN n.key, n.name, n.qualified_name"
    )
    for label in CONTAINED_LABELS
}
DISAPPEARED_BY_LABEL = {
    label: (
        f"MATCH (n:{label} {{system_id: $sid}}) "
        "WHERE n.last_seen < $t0 AND coalesce(n.missing, false) = false "
        "RETURN n.key, n.name, n.qualified_name"
    )
    for label in CONTAINED_LABELS
}
MARK_MISSING_BY_LABEL = {
    label: (
        f"UNWIND $keys AS k MATCH (n:{label} {{key: k}}) "
        "SET n.missing = true SET n.missing_since = $t0"
    )
    for label in CONTAINED_LABELS
}
GROWTH = (
    "MATCH (t:Table {system_id: $sid}) "
    "WHERE t.last_seen >= $t0 AND t.est_rows_prev IS NOT NULL "
    "RETURN t.key, t.name, t.qualified_name, t.est_rows_prev, t.est_rows"
)
_INSERT_DELTA = (
    "INSERT INTO argos.inventory_deltas (run_id, kind, node_label, node_key, detail) "
    "VALUES (%s, %s, %s, %s, %s::jsonb) "
    "ON CONFLICT (run_id, kind, node_key) DO NOTHING"
)
_COLUMNS = ("key", "name", "qualified_name")


@dataclass(frozen=True, slots=True)
class Delta:
    kind: str
    label: str
    node_key: str
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DeltaReport:
    run_id: str
    system_id: str
    baseline: bool
    counts: dict[str, int]
    deltas: tuple[Delta, ...]


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def is_anomalous_growth(before: int | None, now: int, factor: float = GROWTH_FACTOR) -> bool:
    return before is not None and before > GROWTH_MIN_ROWS and now > before * factor


def _load_run(dsn: str, system_id: str, run_id: str) -> tuple[str, datetime, str | None]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT status, started_at, prev_run::text FROM argos.scan_runs "
            "WHERE id = %s AND system_id = %s",
            (run_id, system_id),
        ).fetchone()
    if row is None:
        raise LookupError(f"unknown scan run {run_id} for system {system_id}")
    return str(row[0]), row[1], row[2]


def _record(dsn: str, report: DeltaReport) -> None:
    journal = PostgresJournal(dsn)
    with psycopg.connect(dsn) as conn:
        for delta in report.deltas:
            conn.execute(
                _INSERT_DELTA,
                (report.run_id, delta.kind, delta.label, delta.node_key, json.dumps(delta.detail)),
            )
        payload = {"system_id": report.system_id, "run_id": report.run_id, "counts": report.counts}
        journal.append(JOURNAL_ACTOR, "inventory.delta", payload, conn=conn)


def _node_delta(kind: str, label: str, row: dict[str, Any]) -> Delta:
    detail = {"name": row["name"], "qualified_name": row["qualified_name"] or row["name"]}
    return Delta(kind, label, str(row["key"]), detail)


def compute_deltas(
    store: GraphStore,
    dsn: str,
    bus: EventPublisher,
    system_id: str,
    run_id: str,
    growth_factor: float = GROWTH_FACTOR,
) -> DeltaReport:
    status, started_at, prev_run = _load_run(dsn, system_id, run_id)
    if status != "completed":
        raise ValueError(f"deltas need a completed scan run, got {status!r}")
    if prev_run is None:
        empty = {kind: 0 for kind in DELTA_KINDS}
        return DeltaReport(run_id, system_id, True, empty, ())
    t0 = iso_utc(started_at)
    params = {"sid": system_id, "t0": t0}
    deltas: list[Delta] = []
    gone: list[Delta] = []
    growth_columns = ("key", "name", "qualified_name", "before", "now")
    with store.connection() as conn:
        for label in CONTAINED_LABELS:
            appeared = store.query(APPEARED_BY_LABEL[label], params, _COLUMNS, conn)
            deltas += [_node_delta("appeared", label, r) for r in appeared]
        for label in CONTAINED_LABELS:
            missing = store.query(DISAPPEARED_BY_LABEL[label], params, _COLUMNS, conn)
            found = [_node_delta("disappeared", label, r) for r in missing]
            if found:
                keys = {"keys": [d.node_key for d in found], "t0": t0}
                store.execute(MARK_MISSING_BY_LABEL[label], keys, conn)
            gone += found
        growth = store.query(GROWTH, params, growth_columns, conn)
    deltas += gone
    for row in growth:
        if is_anomalous_growth(row["before"], int(row["now"]), growth_factor):
            detail = {
                "name": row["name"],
                "qualified_name": row["qualified_name"],
                "before": row["before"],
                "now": row["now"],
            }
            deltas.append(Delta("anomalous_growth", "Table", str(row["key"]), detail))
    counts = {kind: sum(1 for d in deltas if d.kind == kind) for kind in DELTA_KINDS}
    report = DeltaReport(run_id, system_id, False, counts, tuple(deltas))
    _record(dsn, report)
    ready = {"system_id": system_id, "run_id": run_id, "counts": counts}
    asyncio.run(bus.publish("argos.discovery.delta_ready", "discovery.delta_ready.v1", ready))
    return report
