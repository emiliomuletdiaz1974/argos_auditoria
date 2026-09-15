"""Thin layer over Apache AGE for the inventory graph (ARG-021, deviation note ARG-021-023).

Cypher runs through ag_catalog.cypher() with its parameters bound by psycopg on the server: AGE
requires the third argument to be a real parameter, never a formatted literal.
"""

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg

GRAPH = "inventory"
_SETUP = "LOAD 'age'; SET search_path = ag_catalog, \"$user\", public;"
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_AGTYPE_SUFFIXES = ("::vertex", "::edge", "::path")


def decode_agtype(value: Any) -> Any:
    """Turn an agtype result into Python values; queries return scalars, maps and lists."""
    if value is None:
        return None
    text = str(value)
    for suffix in _AGTYPE_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return json.loads(text)


class GraphStore:
    def __init__(self, dsn: str, graph: str = GRAPH) -> None:
        if not _IDENTIFIER.match(graph):
            raise ValueError(f"invalid graph name: {graph!r}")
        self._dsn = dsn
        self.graph = graph

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[Any]]:
        """A connection with AGE loaded; it commits when the block ends without error."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(_SETUP)
            yield conn

    def statement(self, cypher: str, columns: Sequence[str]) -> str:
        if "$$" in cypher:
            raise ValueError("cypher text must not contain $$")
        if not columns or any(not _IDENTIFIER.match(c) for c in columns):
            raise ValueError(f"invalid result columns: {list(columns)!r}")
        body = cypher.replace("%", "%%")  # psycopg placeholders: a literal % must be doubled
        # Quoted: result columns such as "table" or "column" are reserved words in SQL.
        typed = ", ".join(f'"{c}" agtype' for c in columns)
        return f"SELECT * FROM cypher('{self.graph}', $$ {body} $$, %s) AS ({typed})"  # noqa: S608

    def query(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
        columns: Sequence[str] = ("v",),
        conn: psycopg.Connection[Any] | None = None,
    ) -> list[dict[str, Any]]:
        sql = self.statement(cypher, columns)
        payload = json.dumps(dict(params or {}), default=str)
        if conn is not None:
            rows = conn.execute(sql, (payload,)).fetchall()
        else:
            with self.connection() as own:
                rows = own.execute(sql, (payload,)).fetchall()
        return [
            {column: decode_agtype(value) for column, value in zip(columns, row, strict=True)}
            for row in rows
        ]

    def execute(
        self,
        cypher: str,
        params: Mapping[str, Any] | None = None,
        conn: psycopg.Connection[Any] | None = None,
    ) -> None:
        self.query(cypher, params, ("v",), conn)
