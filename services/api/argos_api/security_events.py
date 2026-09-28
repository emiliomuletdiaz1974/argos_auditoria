"""F09-08 · what the API writes in the security log, and how it exposes it.

The API records who tried what: tokens missing or rejected, permissions refused, second factors
asked for, and every use of an administration permission. The detail keeps the route template,
never the path itself, which may carry data of the client (a node key, a name).

`security_metrics` is what Prometheus scrapes: the events by kind and outcome (folded bursts count
for as many as they folded) and whether the chain still verifies.
"""

import logging
import threading
import time
from typing import Any

import psycopg
from fastapi import Request

from argos_common import security_log
from argos_common.logs import loki_dropped

SOURCE = "argos-api"
_log = logging.getLogger(__name__)


def route_of(request: Request) -> str:
    """The template of the route (`/api/v1/findings/{finding_id}`), never the concrete path."""
    route = request.scope.get("route")
    return str(getattr(route, "path", "")) or "unmatched"


def security_event(
    request: Request,
    kind: str,
    actor: str,
    outcome: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Record without ever failing the request: a log that cannot be written is logged itself."""
    app = request.scope.get("app")
    dsn: str | None = getattr(app.state, "dsn", None) if app is not None else None
    if not dsn:
        return
    client = request.client.host if request.client else "unknown"
    origin = actor if actor.startswith("user:") else f"client:{client}"
    full = {"method": request.method, "route": route_of(request), **(detail or {})}
    try:
        security_log.log(dsn).record(kind, actor, outcome, full, source=SOURCE, origin=origin)
    except (psycopg.Error, OSError, ValueError):
        _log.exception("security event not recorded", extra={"kind": kind})


_COUNTS = (
    "SELECT kind, outcome,"
    " sum(CASE WHEN detail ? 'suppressed' THEN (detail->>'suppressed')::bigint ELSE 1 END)"
    " FROM security.events GROUP BY kind, outcome ORDER BY kind, outcome"
)


# Walking the whole chain grows with the log: once every five minutes, the last answer in between
# (quality review QA-013). The health service verifies the same chain on its own schedule.
CHAIN_INTERVAL = 300.0
_monotonic = time.monotonic
_chain_lock = threading.Lock()
_chain: dict[str, tuple[float, bool]] = {}


def reset_chain_cache() -> None:
    with _chain_lock:
        _chain.clear()


def chain_intact(dsn: str) -> bool:
    with _chain_lock:
        known = _chain.get(dsn)
        if known is not None and _monotonic() - known[0] < CHAIN_INTERVAL:
            return known[1]
    intact = bool(security_log.verify_chain(dsn).intact)
    with _chain_lock:
        _chain[dsn] = (_monotonic(), intact)
    return intact


def security_metrics(dsn: str) -> str:
    """Prometheus text format: `argos_security_events_total` and `argos_security_chain_ok`."""
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(_COUNTS).fetchall()
    lines = [
        "# HELP argos_security_events_total Security events by kind and outcome.",
        "# TYPE argos_security_events_total counter",
    ]
    lines += [
        f'argos_security_events_total{{kind="{kind}",outcome="{outcome}"}} {int(total)}'
        for kind, outcome, total in rows
    ]
    intact = chain_intact(dsn)
    lines += [
        "# HELP argos_security_chain_ok 1 while the chain of the security log verifies.",
        "# TYPE argos_security_chain_ok gauge",
        f"argos_security_chain_ok {int(intact)}",
    ]
    return "\n".join(lines) + "\n"


_RESTORE = (
    "SELECT extract(epoch FROM max(tested_at) FILTER (WHERE result = 'passed')),"
    " (array_agg(result ORDER BY tested_at DESC))[1] FROM argos.restore_tests"
)


def backup_metrics(dsn: str) -> str:
    """F09-12 (ARG-089): when a restore test last passed, and whether the last one did.

    A backup only exists when its restoration has been tried: with no test that passed, the
    timestamp is 0 and the alert of a stale test fires by itself.
    """
    with psycopg.connect(dsn) as conn:
        row = conn.execute(_RESTORE).fetchone()
    passed_at, last = row or (None, None)
    lines = [
        "# HELP argos_backup_last_restore_test_timestamp_seconds When a restore test last passed.",
        "# TYPE argos_backup_last_restore_test_timestamp_seconds gauge",
        f"argos_backup_last_restore_test_timestamp_seconds {int(passed_at or 0)}",
    ]
    if last is not None:
        lines += [
            "# HELP argos_backup_last_restore_test_success 1 if the last restore test passed.",
            "# TYPE argos_backup_last_restore_test_success gauge",
            f"argos_backup_last_restore_test_success {int(last == 'passed')}",
        ]
    return "\n".join(lines) + "\n"


def list_events(dsn: str, limit: int, after: tuple[str, str] | None = None) -> list[dict[str, Any]]:
    at, seq = after if after else (None, None)
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT seq, at, actor, source, kind, outcome, detail FROM security.events"
            " WHERE (%(at)s::timestamptz IS NULL OR (at, seq) < (%(at)s, %(seq)s::bigint))"
            " ORDER BY at DESC, seq DESC LIMIT %(limit)s",
            {"at": at, "seq": int(seq) if seq is not None else None, "limit": limit},
        ).fetchall()
    return [
        {
            "seq": row[0],
            "at": row[1].isoformat(),
            "actor": row[2],
            "source": row[3],
            "kind": row[4],
            "outcome": row[5],
            "detail": row[6],
            # the order of the cursor: the instant, then the sequence written to sort as text
            "_order": f"{row[0]:020d}",
        }
        for row in rows
    ]


def log_metrics() -> str:
    """F10-05 (ARG-093): the log lines the API dropped instead of sending them to Loki."""
    return (
        "# HELP argos_log_records_dropped_total Log lines dropped instead of sent to Loki.\n"
        "# TYPE argos_log_records_dropped_total counter\n"
        f'argos_log_records_dropped_total{{service="argos-api"}} {loki_dropped()}\n'
    )
