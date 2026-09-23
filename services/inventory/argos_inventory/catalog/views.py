"""Readers of the relational catalog of the inventory (ARG-026)."""

from typing import Any

import psycopg
from psycopg.rows import dict_row

_CATALOG_COLUMNS = (
    "SELECT * FROM argos.catalog_columns WHERE system_id = %s ORDER BY qualified_name, category"
)
_SYSTEMS = (
    "SELECT id, name, kind, environment, owner, read_only_verified_at, created_at"
    " FROM argos.systems"
    " WHERE (%(at)s::timestamptz IS NULL OR (created_at, id::text) < (%(at)s, %(id)s))"
    " ORDER BY created_at DESC, id DESC LIMIT %(limit)s"
)
_PENDING_BY_SYSTEM = (
    "SELECT system_id, count(*)::integer AS pending_review FROM argos.review_queue"
    " WHERE status = 'pending' GROUP BY system_id"
)


def refresh_catalog(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT argos.refresh_catalog()")


def _rows(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return list(conn.execute(sql, params).fetchall())


def _rows_named(dsn: str, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return list(conn.execute(sql, params).fetchall())


def catalog_columns(dsn: str, system_id: str) -> list[dict[str, Any]]:
    return _rows(dsn, _CATALOG_COLUMNS, (system_id,))


def coverage(dsn: str, system_id: str | None = None) -> list[dict[str, Any]]:
    """The catalogue coverage of every system, or of one: filtered in SQL, not after reading."""
    return _rows_named(
        dsn,
        "SELECT * FROM argos.catalog_coverage "
        "WHERE (%(system_id)s::text IS NULL OR system_id::text = %(system_id)s) "
        "ORDER BY system_name",
        {"system_id": system_id},
    )


def freshness(dsn: str) -> list[dict[str, Any]]:
    return _rows(dsn, "SELECT * FROM argos.catalog_freshness ORDER BY name")


def systems(dsn: str, limit: int, after: tuple[str, str] | None = None) -> list[dict[str, Any]]:
    """The registered systems, newest first, in keyset order so a page never repeats a row."""
    at, ident = after if after else (None, None)
    rows = _rows_named(dsn, _SYSTEMS, {"at": at, "id": ident, "limit": limit})
    for row in rows:
        row["id"] = str(row["id"])
        row["created_at"] = row["created_at"].isoformat()
        if row["read_only_verified_at"] is not None:
            row["read_only_verified_at"] = row["read_only_verified_at"].isoformat()
    return rows


def pending_review_by_system(dsn: str) -> dict[str, int]:
    """How many columns wait for a person, per system."""
    return {str(r["system_id"]): int(r["pending_review"]) for r in _rows(dsn, _PENDING_BY_SYSTEM)}
