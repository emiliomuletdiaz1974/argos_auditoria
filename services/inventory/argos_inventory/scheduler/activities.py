"""Inventory scheduler activities: every I/O of the rescan pipeline lives here (ARG-030)."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Any

import psycopg
from temporalio import activity
from temporalio.exceptions import ApplicationError

from argos_common.secret_stores import SecretStore
from argos_connector.budget import LoadBudget
from argos_inventory.ai_discovery.detect import discover_ai
from argos_inventory.catalog.views import refresh_catalog
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.discovery.events import EventPublisher
from argos_inventory.discovery.probes import run_probe
from argos_inventory.discovery.scanner import scan_system
from argos_inventory.flows.detect import detect_engine_links, detect_structural
from argos_inventory.graph.model import system_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.scheduler.policy import ScoredSystem, SystemState, rank_systems
from argos_inventory.versioning.deltas import compute_deltas

INGESTION_PENDING = "IngestionPending"
RECENT_WINDOW_DAYS = 7

_SYSTEM_STATES = (
    "SELECT s.id::text, s.name, s.kind, s.connection -> 'config' -> 'budget', "
    "(SELECT max(r.finished_at) FROM argos.scan_runs r "
    "  WHERE r.system_id = s.id AND r.status = 'completed'), "
    "(SELECT count(*) FROM argos.inventory_deltas d JOIN argos.scan_runs r ON r.id = d.run_id "
    "  WHERE r.system_id = s.id AND d.kind = 'appeared' "
    "  AND r.finished_at > %s - make_interval(days => %s)), "
    "EXISTS (SELECT 1 FROM argos.scan_runs r WHERE r.system_id = s.id AND r.status = 'running') "
    "FROM argos.systems s ORDER BY s.id"
)
_AI_PENDING = (
    "MATCH (s:System)-[:USES_MODEL]->(a:AISystem) WHERE a.status = 'pending' RETURN s.id, count(a)"
)
_LAST_INGESTED = "MATCH (s:System {key: $key}) RETURN s.last_scan_run"


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    system_id: str
    run_id: str
    status: str
    events: int
    error: str | None


class ThreadSafePublisher:
    """Lets synchronous code in a worker thread publish on a bus owned by the event loop.

    `compute_deltas` publishes with `asyncio.run` in its own thread; a NATS connection belongs to
    the loop that opened it, so the publication is handed back to that loop.
    """

    def __init__(self, bus: EventPublisher, loop: asyncio.AbstractEventLoop) -> None:
        self._bus = bus
        self._loop = loop

    async def publish(
        self, subject: str, event_type: str, data: dict[str, Any], audit: bool = False
    ) -> int:
        future = asyncio.run_coroutine_threadsafe(
            self._bus.publish(subject, event_type, data, audit), self._loop
        )
        return await asyncio.wrap_future(future)


def _in_window(system_id: str, budget: dict[str, Any] | None) -> bool:
    try:
        return LoadBudget(system_id, budget or None).in_window()
    except (ValueError, KeyError, TypeError):  # a broken budget never authorises probing
        return False


class InventoryActivities:
    def __init__(self, dsn: str, secrets: SecretStore, bus: EventPublisher) -> None:
        self._dsn = dsn
        self._secrets = secrets
        self._bus = bus
        self._store = GraphStore(dsn)

    @activity.defn(name="score_systems")
    async def score_systems(self) -> list[ScoredSystem]:
        now = datetime.now(UTC)
        states = await asyncio.to_thread(self._states, now)
        return rank_systems(states, now)

    @activity.defn(name="run_scan")
    async def run_scan(self, system_id: str, run_id: str) -> ScanOutcome:
        summary = await scan_system(self._dsn, self._secrets, self._bus, system_id, run_id)
        return ScanOutcome(system_id, summary.run_id, summary.status, summary.events, summary.error)

    @activity.defn(name="compute_run_deltas")
    async def compute_run_deltas(self, system_id: str, run_id: str) -> dict[str, int]:
        if await asyncio.to_thread(self._last_ingested, system_id) != run_id:
            raise ApplicationError(f"scan run {run_id} is not ingested yet", type=INGESTION_PENDING)
        publisher = ThreadSafePublisher(self._bus, asyncio.get_running_loop())
        report = await asyncio.to_thread(
            compute_deltas, self._store, self._dsn, publisher, system_id, run_id
        )
        return {kind: int(count) for kind, count in report.counts.items()}

    @activity.defn(name="analyze_system")
    async def analyze_system(self, system_id: str) -> dict[str, int]:
        return await asyncio.to_thread(self._analyze, system_id)

    @activity.defn(name="refresh_inventory")
    async def refresh_inventory(self) -> dict[str, int]:
        return await asyncio.to_thread(self._refresh)

    def _states(self, now: datetime) -> list[SystemState]:
        pending = {
            str(r["system"]): int(r["n"])
            for r in self._store.query(_AI_PENDING, columns=("system", "n"))
        }
        with psycopg.connect(self._dsn) as conn:
            rows = conn.execute(_SYSTEM_STATES, (now, RECENT_WINDOW_DAYS)).fetchall()
        return [
            SystemState(
                system_id=sid,
                name=name,
                kind=kind,
                last_completed=last,
                recent_new=int(recent),
                ai_pending=pending.get(sid, 0),
                running=bool(running),
                in_window=_in_window(sid, budget),
            )
            for sid, name, kind, budget, last, recent, running in rows
        ]

    def _last_ingested(self, system_id: str) -> str | None:
        rows = self._store.query(_LAST_INGESTED, {"key": system_key(system_id)}, ("run",))
        return None if not rows or rows[0]["run"] is None else str(rows[0]["run"])

    def _analyze(self, system_id: str) -> dict[str, int]:
        with psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT kind FROM argos.systems WHERE id = %s", (system_id,)
            ).fetchone()
        if row is None or row[0] != "rdbms":
            return {"classified": 0, "engine_links": 0, "probe_failures": 0}
        runner = partial(run_probe, self._dsn, self._secrets)
        classified = classify_new_columns(self._store, runner, system_id)
        flows = detect_engine_links(self._store, self._dsn, runner, system_id)
        return {
            "classified": classified.dictionary + classified.validated,
            "engine_links": flows.engine_links,
            "probe_failures": classified.probe_failures + flows.probe_failures,
        }

    def _refresh(self) -> dict[str, int]:
        structural = detect_structural(self._store)
        ai = discover_ai(self._store)
        refresh_catalog(self._dsn)
        return {"structural_flows": structural, "ai_signals": ai.routes + ai.files + ai.columns}
