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
# Identities are the roles of the system: a revoked role no longer shows up in a scan and
# disappears like a table does (QA-032).
CONTAINED_LABELS = ("Schema", "Table", "Column", "FileArea", "Identity")
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
# A grant not seen again is a revoked access: it is marked, like everything else (QA-032).
REVOKED_ACCESS = (
    "MATCH (i:Identity {system_id: $sid})-[a:CAN_ACCESS]->(t:Table) "
    "WHERE a.last_seen < $t0 AND coalesce(a.missing, false) = false "
    "RETURN i.key, i.name, t.qualified_name, t.key"
)
MARK_ACCESS_REVOKED = (
    "UNWIND $pairs AS p "
    "MATCH (i:Identity {key: p.identity})-[a:CAN_ACCESS]->(t:Table {key: p.table}) "
    "SET a.missing = true SET a.missing_since = $t0"
)
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


def _record(dsn: str, report: DeltaReport, conn: Any) -> None:
    """The deltas, their journal entry and the mark of the run, in the caller's transaction."""
    journal = PostgresJournal(dsn)
    for delta in report.deltas:
        conn.execute(
            _INSERT_DELTA,
            (report.run_id, delta.kind, delta.label, delta.node_key, json.dumps(delta.detail)),
        )
    payload = {"system_id": report.system_id, "run_id": report.run_id, "counts": report.counts}
    journal.append(JOURNAL_ACTOR, "inventory.delta", payload, conn=conn)
    conn.execute("UPDATE argos.scan_runs SET deltas_at = now() WHERE id = %s", (report.run_id,))


def _recorded(dsn: str, system_id: str, run_id: str) -> DeltaReport | None:
    """The report of a run whose deltas were already computed: a retry gives it back (QA-030)."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT deltas_at FROM argos.scan_runs WHERE id = %s", (run_id,)
        ).fetchone()
        if row is None or row[0] is None:
            return None
        rows = conn.execute(
            "SELECT kind, node_label, node_key, detail FROM argos.inventory_deltas"
            " WHERE run_id = %s ORDER BY id",
            (run_id,),
        ).fetchall()
    deltas = tuple(
        Delta(str(k), str(label), str(key), dict(detail)) for k, label, key, detail in rows
    )
    counts = {kind: sum(1 for d in deltas if d.kind == kind) for kind in DELTA_KINDS}
    return DeltaReport(run_id, system_id, False, counts, deltas)


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
    done = _recorded(dsn, system_id, run_id)
    if done is not None:
        _announce(bus, done)  # the retry announces what the first attempt may not have
        return done
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
        revoked = store.query(
            REVOKED_ACCESS, params, ("identity", "grantee", "table_name", "table"), conn
        )
        if revoked:
            pairs = [{"identity": r["identity"], "table": r["table"]} for r in revoked]
            store.execute(MARK_ACCESS_REVOKED, {"pairs": pairs, "t0": t0}, conn)
            gone += [
                Delta(
                    "disappeared",
                    "CAN_ACCESS",
                    f"{r['identity']}->{r['table']}",
                    {"name": str(r["grantee"]), "qualified_name": str(r["table_name"])},
                )
                for r in revoked
            ]
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
        # The marks, the deltas and the journal entry commit together, or none does (QA-030).
        _record(dsn, report, conn)
    _announce(bus, report)
    return report


def _announce(bus: EventPublisher, report: DeltaReport) -> None:
    ready = {"system_id": report.system_id, "run_id": report.run_id, "counts": report.counts}
    asyncio.run(
        bus.publish(
            "argos.discovery.delta_ready",
            "discovery.delta_ready.v1",
            ready,
        )
    )


def node_deltas(dsn: str, node_key: str, limit: int = 50) -> list[dict[str, Any]]:
    """What happened to a node, newest first: when it appeared, disappeared or grew too fast."""
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT d.kind, d.detail, d.created_at, d.run_id::text FROM argos.inventory_deltas d"
            " WHERE d.node_key = %s ORDER BY d.created_at DESC, d.id DESC LIMIT %s",
            (node_key, limit),
        ).fetchall()
    return [
        {"kind": row[0], "detail": row[1], "at": row[2].isoformat(), "run_id": row[3]}
        for row in rows
    ]
