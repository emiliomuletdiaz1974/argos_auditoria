"""Discovery scanner: runs the read-only probes of one system and publishes what they saw.

Component ARG-022 (deviation note ARG-021-023). Every run is a row of argos.scan_runs, the time cut
that ARG-023 compares against. Failures never escape the run: it records the error type only,
because driver messages may carry customer data.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from argos_common.ids import uuid7
from argos_common.secret_stores import SecretStore
from argos_connector.base import Connector
from argos_connector.probes import ProbeSpec

from .events import (
    EventPublisher,
    access_event,
    discovery_target,
    events_for,
    scan_completed_event,
)
from .probes import RegisteredSystem, load_system, open_connector

MAX_ACCESS_PROBES = 500  # tables per run with a privileges probe; the load budget still rules

_START = (
    "INSERT INTO argos.scan_runs (id, system_id, started_at, prev_run) VALUES (%s, %s, %s, "
    "(SELECT id FROM argos.scan_runs WHERE system_id = %s AND status = 'completed' "
    "ORDER BY started_at DESC LIMIT 1))"
)
_FINISH = (
    "UPDATE argos.scan_runs SET status = %s, finished_at = %s, events = %s, error = %s "
    "WHERE id = %s"
)


@dataclass(frozen=True, slots=True)
class ScanSummary:
    run_id: str
    system_id: str
    status: str
    events: int
    failed_probes: int
    error: str | None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _start_run(dsn: str, run_id: str, system_id: str, started: datetime) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(_START, (run_id, system_id, started, system_id))


def _finish_run(
    dsn: str, run_id: str, status: str, finished: datetime, events: int, error: str | None
) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(_FINISH, (status, finished, events, error, run_id))


async def _run_probes(
    connector: Connector,
    system: RegisteredSystem,
    bus: EventPublisher,
    run_id: str,
    observed_at: str,
) -> tuple[int, int, bool]:
    """Publish what the probes saw; returns (events, failed probes, discovery succeeded)."""
    spec = ProbeSpec("scan_schema", discovery_target(system))
    result = await asyncio.to_thread(connector.execute, spec)
    if not result.ok:
        return 0, 1, False
    published = 0
    for event in events_for(system, result, run_id, observed_at):
        await bus.publish(event.subject, event.event_type, event.data)
        published += 1
    failed = 0
    if "privileges" in getattr(type(connector), "CONFIG_CHECKS", {}):
        schemas = result.data.get("schemas", {})
        tables = [(s, t) for s in sorted(schemas) for t in sorted(schemas[s])]
        for schema, table in tables[:MAX_ACCESS_PROBES]:
            params = {"check": "privileges", "schema": schema, "table": table}
            check_spec = ProbeSpec("check_config", f"{schema}.{table}", params=params)
            check = await asyncio.to_thread(connector.execute, check_spec)
            if not check.ok:
                failed += 1
                continue
            event = access_event(system, check, run_id, observed_at, schema, table)
            await bus.publish(event.subject, event.event_type, event.data)
            published += 1
    return published, failed, True


async def scan_system(
    dsn: str,
    store: SecretStore,
    bus: EventPublisher,
    system_id: str,
    run_id: str | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> ScanSummary:
    run = run_id or str(uuid7())
    started = now()
    await asyncio.to_thread(_start_run, dsn, run, system_id, started)
    published, failed = 0, 0
    status: str = "completed"
    error: str | None = None
    try:
        system = await asyncio.to_thread(load_system, dsn, system_id)
        connector = await asyncio.to_thread(open_connector, dsn, store, system)
        try:
            published, failed, discovered = await _run_probes(
                connector, system, bus, run, now().isoformat()
            )
        finally:
            await asyncio.to_thread(connector.close)
        if not discovered:
            status, error = "failed", "discovery_probe_failed"
    except Exception as exc:  # the type only: driver messages may carry customer data
        status, error = "failed", type(exc).__name__
    finished = now()
    await asyncio.to_thread(_finish_run, dsn, run, status, finished, published, error)
    completed = scan_completed_event(
        system_id, run, status, started.isoformat(), finished.isoformat(), published, failed, error
    )
    await bus.publish(completed.subject, completed.event_type, completed.data)
    return ScanSummary(run, system_id, status, published, failed, error)
