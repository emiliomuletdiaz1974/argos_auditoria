"""ARG-098 · the limits of each size of the appliance and where it stands against them (F10-08).

The sizes (S, M and L) promise how many systems, inventory assets, parallel campaigns and daily AI
tokens they hold (`platform/operation/sizes.yaml`). The appliance measures itself against its size,
shows the position in bands (green, amber from 80 %, red at 100 %) and refuses honestly what would
exceed it: with the figures and with what can be done. A snapshot a day keeps thirteen months of
history in `argos.capacity_snapshots`; it never leaves the appliance.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import yaml

from argos_common.errors import ArgosError

DIMENSIONS = ("systems", "assets", "parallel_campaigns", "ai_tokens_per_day")
AMBER = 0.8
HISTORY = "13 months"
_WORDS = {
    "systems": "sistemas registrados",
    "assets": "activos del inventario",
    "parallel_campaigns": "campañas en paralelo",
    "ai_tokens_per_day": "tokens de IA en 24 horas",
}
_MEASURES = {
    "systems": "SELECT count(*) FROM argos.systems",
    "assets": "SELECT coalesce((SELECT node_count FROM argos.inventory_snapshots"
    " ORDER BY taken_at DESC LIMIT 1), 0)",
    # A campaign takes a place while it runs, or while it waits at a gate that has not expired
    # (the 72 hours of GATE_TIMEOUT). Pinned but never launched, or abandoned at a gate, it
    # takes none: it puts no load on the sources.
    "parallel_campaigns": "SELECT count(*) FROM argos.campaigns c WHERE c.status = 'running'"
    " OR (c.status = 'pinned' AND EXISTS (SELECT 1 FROM argos.approval_requests r"
    " WHERE r.campaign_id = c.id AND r.requested_at > now() - interval '72 hours'))",
    "ai_tokens_per_day": "SELECT coalesce(sum(tokens_in + tokens_out), 0) FROM argos.ai_usage"
    " WHERE created_at > now() - interval '24 hours'",
}


class CapacityExceededError(ArgosError):
    """What was asked would take the appliance beyond its size."""


def load_sizes(path: Path) -> dict[str, dict[str, int]]:
    sizes = yaml.safe_load(path.read_text(encoding="utf-8"))["sizes"]
    return {str(name): {d: int(limits[d]) for d in DIMENSIONS} for name, limits in sizes.items()}


def limits_of(path: Path, size: str) -> dict[str, int]:
    sizes = load_sizes(path)
    if size not in sizes:
        raise ValueError(f"unknown size {size!r}: the sizes are {sorted(sizes)}")
    return sizes[size]


def band(used: float, limit: float) -> str:
    ratio = used / limit if limit else 1.0
    if ratio >= 1:
        return "red"
    return "amber" if ratio >= AMBER else "green"


def check(limits: Mapping[str, int], dimension: str, used: int, size: str = "S") -> None:
    """Refuse when one more would exceed the limit, saying the figures and the options."""
    limit = limits[dimension]
    if used + 1 <= limit:
        return
    raise CapacityExceededError(
        f"La talla {size} admite {limit} {_WORDS[dimension]} y ya hay {used}. "
        "Opciones: reducir la carga (retirar lo que ya no se audita), ampliar la talla del "
        "appliance, o leer el informe de capacidad (GET /api/v1/operations/capacity) para decidir.",
        details={"dimension": dimension, "used": used, "limit": limit, "size": size},
    )


def measure(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn) as conn:
        found = {}
        for dimension, query in _MEASURES.items():
            row = conn.execute(query).fetchone()
            found[dimension] = int(row[0]) if row and row[0] is not None else 0
    return found


def usage(dsn: str, size: str, limits: Mapping[str, int]) -> list[dict[str, Any]]:
    used = measure(dsn)
    return [
        {
            "dimension": d,
            "used": used[d],
            "limit": limits[d],
            "ratio": round(used[d] / limits[d], 4) if limits[d] else 1.0,
            "band": band(used[d], limits[d]),
            "size": size,
        }
        for d in DIMENSIONS
    ]


def enforce(dsn: str, size: str, limits: Mapping[str, int], dimension: str) -> None:
    check(limits, dimension, measure(dsn)[dimension], size)


def take_snapshot(
    dsn: str, size: str, limits: Mapping[str, int], at: datetime | None = None
) -> None:
    """Today's position, once a day; what is older than thirteen months goes."""
    when = at or datetime.now(UTC)
    used = measure(dsn)
    with psycopg.connect(dsn) as conn:
        for d in DIMENSIONS:
            conn.execute(
                "INSERT INTO argos.capacity_snapshots (taken_on, dimension, used, capacity, size)"
                " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (taken_on, dimension) DO UPDATE"
                " SET used = EXCLUDED.used, capacity = EXCLUDED.capacity, size = EXCLUDED.size",
                (when.date(), d, used[d], limits[d], size),
            )
        conn.execute(
            "DELETE FROM argos.capacity_snapshots WHERE taken_on < current_date - %s::interval",
            (HISTORY,),
        )


def history(dsn: str) -> list[dict[str, Any]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT taken_on, dimension, used, capacity FROM argos.capacity_snapshots"
            " ORDER BY taken_on, dimension"
        ).fetchall()
    return [
        {"day": day.isoformat(), "dimension": d, "used": int(used), "limit": int(cap)}
        for day, d, used, cap in rows
    ]
