"""Reproducible capacity benchmark of the inventory pipeline on synthetic metadata (§3.10).

It measures what ARGOS itself costs per table: ingestion into the graph, deltas between two scans,
dictionary classification, a snapshot and selector pages. Source probe latency is not part of it:
the real figure for 200 systems and 50,000 tables is measured on appliance hardware.
"""

import asyncio
import json
import math
import os
import platform
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from argos_connector.probes import ProbeResult, ProbeSpec
from argos_inventory.api.selector import NODE_COLUMNS, compile_selector, parse_selector
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore
from argos_inventory.ingest.handlers import Ingestor
from argos_inventory.versioning.deltas import compute_deltas, iso_utc
from argos_inventory.versioning.snapshots import take_snapshot

TARGET_TABLES = 50_000
TARGET_FULL_SCAN_HOURS = 24.0
TARGET_INCREMENTAL_HOURS = 2.0
TARGET_SELECTOR_MS = 2000.0
SELECTOR_PAGES = 5
SELECTOR_PAGE_SIZE = 100
BASE_COLUMNS = (
    "id",
    "national_id",
    "full_name",
    "birth_date",
    "email",
    "diagnosis_code",
    "amount_cents",
    "status",
    "department",
    "created_at",
    "notes",
    "updated_at",
)
SCHEMA = "bench"
CONNECTOR = "argos_sql.generic:SqlConnector"  # recorded as provenance only; never instantiated

_RUN_START = (
    "INSERT INTO argos.scan_runs (id, system_id, started_at, prev_run) VALUES (%s, %s, %s, %s)"
)
_RUN_FINISH = (
    "UPDATE argos.scan_runs SET status = 'completed', finished_at = %s, events = %s WHERE id = %s"
)


@dataclass(frozen=True, slots=True)
class BenchmarkProfile:
    name: str
    systems: int
    tables_per_system: int
    columns_per_table: int
    change_ratio: float

    @property
    def tables(self) -> int:
        return self.systems * self.tables_per_system

    @property
    def changed_per_system(self) -> int:
        return math.ceil(self.tables_per_system * self.change_ratio)


PROFILES = {
    "smoke": BenchmarkProfile("smoke", 4, 25, 6, 0.04),
    "s": BenchmarkProfile("s", 50, 100, 10, 0.01),
    "m": BenchmarkProfile("m", 200, 250, 12, 0.01),
}


@dataclass(frozen=True, slots=True)
class PassTiming:
    tables: int
    ingest_s: float
    deltas_s: float
    classify_s: float
    counts: dict[str, int]

    @property
    def total_s(self) -> float:
        return self.ingest_s + self.deltas_s + self.classify_s


class NullPublisher:
    async def publish(
        self, subject: str, event_type: str, data: dict[str, Any], audit: bool = False
    ) -> int:
        return 0


def _no_probes(system_id: str, spec: ProbeSpec) -> ProbeResult:
    raise RuntimeError("the capacity benchmark never probes a source")


def synthetic_columns(table_index: int, count: int) -> list[dict[str, Any]]:
    window = min(count, len(BASE_COLUMNS))
    names = [BASE_COLUMNS[(table_index + i) % len(BASE_COLUMNS)] for i in range(window)]
    names += [f"attribute_{i}" for i in range(count - window)]
    return [{"name": name, "type": "text", "nullable": True} for name in names]


def pass_tables(profile: BenchmarkProfile, pass_number: int) -> list[int]:
    if pass_number not in (1, 2):
        raise ValueError("the benchmark runs two passes")
    tables = list(range(profile.tables_per_system))
    if pass_number == 1:
        return tables
    changed = profile.changed_per_system
    added = range(profile.tables_per_system, profile.tables_per_system + changed)
    return tables[changed:] + list(added)


def table_event(
    system_id: str, run_id: str, table_index: int, columns: int, at: str, seq: int
) -> dict[str, Any]:
    return {
        "system_id": system_id,
        "run_id": run_id,
        "source_connector": CONNECTOR,
        "probe_id": f"bench-{run_id}",
        "journal_seq": seq,
        "observed_at": at,
        "schema": SCHEMA,
        "table": f"table_{table_index:05d}",
        "est_rows": 1000 + table_index * 10,
        "bytes": 8192 * (1 + table_index),
        "comment": None,
        "columns": synthetic_columns(table_index, columns),
    }


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    rank = max(math.ceil(fraction * len(ordered)) - 1, 0)
    return ordered[min(rank, len(ordered) - 1)]


def hours_for(tables: int, seconds: float, target_tables: int = TARGET_TABLES) -> float:
    if tables <= 0:
        raise ValueError("tables must be positive")
    return round(seconds / tables * target_tables / 3600, 3)


def register_synthetic_systems(dsn: str, profile: BenchmarkProfile) -> list[str]:
    ids = [str(uuid.uuid4()) for _ in range(profile.systems)]
    connection = json.dumps({"secret": "bench/none", "connector": CONNECTOR, "config": {}})
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO argos.systems (id, name, kind, connection) "
            "VALUES (%s, %s, 'rdbms', %s::jsonb)",
            [(sid, f"bench-system-{i:03d}", connection) for i, sid in enumerate(ids)],
        )
    return ids


async def _ingest_tables(
    ingestor: Ingestor, system_id: str, run_id: str, indices: list[int], columns: int, at: str
) -> None:
    for seq, index in enumerate(indices, start=1):
        event = table_event(system_id, run_id, index, columns, at, seq)
        await ingestor.handle(event, {"type": "eu.argos.discovery.table_found.v1"})


def run_pass(
    dsn: str,
    store: GraphStore,
    system_ids: list[str],
    profile: BenchmarkProfile,
    pass_number: int,
    previous: dict[str, str],
) -> tuple[PassTiming, dict[str, str]]:
    bus = NullPublisher()
    ingestor = Ingestor(store, dsn, bus)
    indices = pass_tables(profile, pass_number)
    runs: dict[str, str] = {}
    ingest_s = deltas_s = classify_s = 0.0
    counts = {"appeared": 0, "disappeared": 0, "anomalous_growth": 0}
    for system_id in system_ids:
        run_id = str(uuid.uuid4())
        started = datetime.now(UTC)
        # observed strictly after the run start, as a real probe answer always is
        at = iso_utc(started + timedelta(milliseconds=1))
        clock = time.perf_counter()
        with psycopg.connect(dsn) as conn:
            conn.execute(_RUN_START, (run_id, system_id, started, previous.get(system_id)))
        asyncio.run(
            _ingest_tables(ingestor, system_id, run_id, indices, profile.columns_per_table, at)
        )
        finished = datetime.now(UTC)
        with psycopg.connect(dsn) as conn:
            conn.execute(_RUN_FINISH, (finished, len(indices), run_id))
        completed = {
            "system_id": system_id,
            "run_id": run_id,
            "status": "completed",
            "started_at": iso_utc(started),
            "finished_at": iso_utc(finished),
            "events": len(indices),
            "failed_probes": 0,
            "error": None,
        }
        asyncio.run(ingestor.handle(completed, {"type": "eu.argos.discovery.scan_completed.v1"}))
        ingest_s += time.perf_counter() - clock

        clock = time.perf_counter()
        report = compute_deltas(store, dsn, bus, system_id, run_id)
        deltas_s += time.perf_counter() - clock
        for kind, count in report.counts.items():
            counts[kind] += int(count)

        clock = time.perf_counter()
        classify_new_columns(store, _no_probes, system_id, available=frozenset())
        classify_s += time.perf_counter() - clock
        runs[system_id] = run_id
    timing = PassTiming(
        tables=len(indices) * len(system_ids),
        ingest_s=round(ingest_s, 3),
        deltas_s=round(deltas_s, 3),
        classify_s=round(classify_s, 3),
        counts=counts,
    )
    return timing, runs


def selector_latencies(store: GraphStore) -> list[float]:
    selector = parse_selector({"label": "Column", "category": "personal_data"})
    latencies: list[float] = []
    after: str | None = None
    with store.connection() as conn:
        for _ in range(SELECTOR_PAGES):
            cypher, params = compile_selector(selector, SELECTOR_PAGE_SIZE, after)
            clock = time.perf_counter()
            rows = store.query(cypher, params, NODE_COLUMNS, conn)
            latencies.append(round((time.perf_counter() - clock) * 1000, 3))
            if len(rows) <= SELECTOR_PAGE_SIZE:
                break
            after = str(rows[SELECTOR_PAGE_SIZE - 1]["key"])
    return latencies


def _pass_report(timing: PassTiming) -> dict[str, Any]:
    total = round(timing.total_s, 3)
    return {
        "tables": timing.tables,
        "ingest_s": timing.ingest_s,
        "deltas_s": timing.deltas_s,
        "classify_s": timing.classify_s,
        "total_s": total,
        "tables_per_s": round(timing.tables / total, 1) if total > 0 else None,
        "deltas": timing.counts,
    }


def run_benchmark(dsn: str, profile: BenchmarkProfile) -> dict[str, Any]:
    store = GraphStore(dsn)
    system_ids = register_synthetic_systems(dsn, profile)
    first, runs = run_pass(dsn, store, system_ids, profile, 1, {})
    second, _ = run_pass(dsn, store, system_ids, profile, 2, runs)

    clock = time.perf_counter()
    snapshot = take_snapshot(store, dsn, f"benchmark-{profile.name}")
    snapshot_s = round(time.perf_counter() - clock, 3)
    latencies = selector_latencies(store)
    [nodes] = store.query("MATCH (n) RETURN count(n)", columns=("n",))
    return {
        "profile": asdict(profile),
        "tables": profile.tables,
        "columns": profile.tables * profile.columns_per_table,
        "graph_nodes": int(nodes["n"]),
        "pass1": _pass_report(first),
        "pass2": _pass_report(second),
        "snapshot": {"seconds": snapshot_s, "nodes": snapshot.node_count},
        "selector_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "pages": len(latencies),
        },
        "extrapolated_hours": {
            "full_scan": hours_for(first.tables, first.total_s),
            "rescan": hours_for(second.tables, second.total_s),
        },
        "targets": {
            "tables": TARGET_TABLES,
            "full_scan_hours": TARGET_FULL_SCAN_HOURS,
            "incremental_hours": TARGET_INCREMENTAL_HOURS,
            "selector_ms": TARGET_SELECTOR_MS,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpus": os.cpu_count(),
        },
        "note": "ARGOS pipeline cost only; source probe latency is measured on appliance hardware.",
    }
