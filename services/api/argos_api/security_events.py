"""F09-08 · what the API writes in the security log, and how it exposes it.

The API records who tried what: tokens missing or rejected, permissions refused, second factors
asked for, and every use of an administration permission. The detail keeps the route template,
never the path itself, which may carry data of the client (a node key, a name).

`security_metrics` is what Prometheus scrapes: the events by kind and outcome (folded bursts count
for as many as they folded) and whether the chain still verifies.
"""

import logging
from typing import Any

import psycopg
from fastapi import Request

from argos_common import security_log

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
    intact = security_log.verify_chain(dsn).intact
    lines += [
        "# HELP argos_security_chain_ok 1 while the chain of the security log verifies.",
        "# TYPE argos_security_chain_ok gauge",
        f"argos_security_chain_ok {int(intact)}",
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
