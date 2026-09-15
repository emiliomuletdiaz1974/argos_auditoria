"""Readers of the relational catalog of the inventory (ARG-026)."""

from typing import Any

import psycopg
from psycopg.rows import dict_row

_CATALOG_COLUMNS = (
    "SELECT * FROM argos.catalog_columns WHERE system_id = %s ORDER BY qualified_name, category"
)


def refresh_catalog(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT argos.refresh_catalog()")


def _rows(dsn: str, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return list(conn.execute(sql, params).fetchall())


def catalog_columns(dsn: str, system_id: str) -> list[dict[str, Any]]:
    return _rows(dsn, _CATALOG_COLUMNS, (system_id,))


def coverage(dsn: str) -> list[dict[str, Any]]:
    return _rows(dsn, "SELECT * FROM argos.catalog_coverage ORDER BY system_name")


def freshness(dsn: str) -> list[dict[str, Any]]:
    return _rows(dsn, "SELECT * FROM argos.catalog_freshness ORDER BY name")
