"""Versioned RDF store of the ontology in PostgreSQL, with in-process SPARQL (ARG-032).

A version is written once and never changed. The version in force on a date is the one with the
latest in_force_from not after that date; the date comes from the signed manifest (ARG-040), so
loading an old bundle late cannot change what applied (deviation note ARG-031-033).
"""

import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from rdflib import Graph
from rdflib.query import ResultRow
from rdflib.term import Identifier, Node
from rdflib.util import from_n3

from argos_common.journal_pg import PostgresJournal
from argos_ontology.vocabulary import bind_prefixes

SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
JOURNAL_ACTOR = "system:ontology"
GRAPH_CACHE_SIZE = 4

_SELECT_BUNDLE = (
    "SELECT version, sha256, in_force_from, quads, loaded_at FROM argos.ontology_bundles "
    "WHERE version = %s"
)
_INSERT_BUNDLE = (
    "INSERT INTO argos.ontology_bundles "
    "(version, sha256, manifest, signature, quads, in_force_from) VALUES (%s, %s, %s, %s, %s, %s) "
    "RETURNING loaded_at"
)
_COPY_QUADS = "COPY argos.ontology_quads (bundle, s, p, o) FROM STDIN"
_VERSION_AT = (
    "SELECT version FROM argos.ontology_bundles WHERE in_force_from <= %s "
    "ORDER BY in_force_from DESC, loaded_at DESC LIMIT 1"
)
_QUADS = "SELECT s, p, o FROM argos.ontology_quads WHERE bundle = %s"


class BundleConflictError(ValueError):
    """A version that already exists was offered with different content."""


@dataclass(frozen=True, slots=True)
class BundleRecord:
    version: str
    sha256: str
    in_force_from: date
    quads: int
    loaded_at: datetime


def _record(row: tuple[Any, ...]) -> BundleRecord:
    return BundleRecord(str(row[0]), str(row[1]), row[2], int(row[3]), row[4])


def _term(n3: str) -> Node:
    term = from_n3(n3)
    if not isinstance(term, Node):  # pragma: no cover - stored terms are always valid N3
        raise ValueError(f"cannot rebuild RDF term from {n3!r}")
    return term


def store_version(
    dsn: str,
    version: str,
    in_force_from: date,
    graph: Graph,
    sha256: str,
    manifest: Mapping[str, Any],
    signature: bytes,
) -> BundleRecord:
    """Persist one version with its journal entry; the same content twice is a no-op."""
    if not SEMVER.match(version):
        raise ValueError(f"ontology version must be MAJOR.MINOR.PATCH: {version!r}")
    if not SHA256.match(sha256):
        raise ValueError("sha256 must be 64 lowercase hex characters")
    rows = sorted({(s.n3(), p.n3(), o.n3()) for s, p, o in graph})
    with psycopg.connect(dsn) as conn:
        existing = conn.execute(_SELECT_BUNDLE, (version,)).fetchone()
        if existing is not None:
            if existing[1] != sha256:
                raise BundleConflictError(
                    f"ontology version {version} already loaded with other content"
                )
            return _record(existing)
        inserted = conn.execute(
            _INSERT_BUNDLE,
            (version, sha256, Jsonb(dict(manifest)), signature, len(rows), in_force_from),
        ).fetchone()
        if inserted is None:  # pragma: no cover - INSERT ... RETURNING always yields a row
            raise RuntimeError("ontology bundle insert returned no row")
        with conn.cursor().copy(_COPY_QUADS) as copy:
            for s, p, o in rows:
                copy.write_row((version, s, p, o))
        payload = {
            "version": version,
            "sha256": sha256,
            "quads": len(rows),
            "in_force_from": in_force_from.isoformat(),
        }
        PostgresJournal(dsn).append(JOURNAL_ACTOR, "ontology.load", payload, conn=conn)
    return BundleRecord(version, sha256, in_force_from, len(rows), inserted[0])


def version_in_force(dsn: str, at: date | None = None) -> str:
    moment = at or datetime.now(UTC).date()
    with psycopg.connect(dsn) as conn:
        row = conn.execute(_VERSION_AT, (moment,)).fetchone()
    if row is None:
        raise LookupError(f"no ontology version in force on {moment.isoformat()}")
    return str(row[0])


def bundle_record(dsn: str, version: str) -> BundleRecord:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(_SELECT_BUNDLE, (version,)).fetchone()
    if row is None:
        raise LookupError(f"unknown ontology version: {version}")
    return _record(row)


@functools.lru_cache(maxsize=GRAPH_CACHE_SIZE)
def _load_graph(dsn: str, version: str) -> Graph:
    graph = bind_prefixes(Graph())
    with psycopg.connect(dsn) as conn:
        for s, p, o in conn.execute(_QUADS, (version,)):
            graph.add((_term(s), _term(p), _term(o)))
    return graph


class OntologyStore:
    """SPARQL over one immutable version: the one given, or the one in force on a date."""

    def __init__(self, dsn: str, version: str | None = None, at: date | None = None) -> None:
        if version is not None and at is not None:
            raise ValueError("give a version or a date, not both")
        self.record = bundle_record(dsn, version or version_in_force(dsn, at))
        self.version = self.record.version
        self.graph = _load_graph(dsn, self.version)

    def sparql(
        self, query: str, bindings: Mapping[str, Identifier] | None = None
    ) -> list[ResultRow]:
        """Run a SELECT; bindings are typed rdflib terms, never guessed from their text."""
        result = self.graph.query(query, initBindings=dict(bindings or {}))
        return [row for row in result if isinstance(row, ResultRow)]
