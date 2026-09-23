"""Deterministic classification: name dictionary first, validation in origin second (ARG-024).

A validator with a high acceptance rate wins over the dictionary; the dictionary wins over nothing.
Only acceptance rates ever leave the connector (deviation note ARG-024-025).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from argos_connector.probes import ProbeResult, ProbeSpec
from argos_inventory.graph.store import GraphStore

from .dictionary import (
    DEFAULT_VALIDATORS,
    TABLE_CONTEXT_METHOD,
    VALIDATOR_CATEGORY,
    match_column_in_table,
    match_column_name,
    validator_hints,
)

_log = logging.getLogger(__name__)
DICTIONARY_CONFIDENCE = 0.6
VALIDATOR_ACCEPT = 0.9
SAMPLE_SIZE = 200

ProbeRunner = Callable[[str, ProbeSpec], ProbeResult]

# Per label with the indexed system_id instead of walking CONTAINS*2 from the System (F03-15).
UNCLASSIFIED = (
    "MATCH (t:Table {system_id: $sid})-[:CONTAINS]->(c:Column) "
    "WHERE NOT exists((c)-[:CLASSIFIED_AS]->()) AND coalesce(c.missing, false) = false "
    "RETURN c.key, c.name, t.qualified_name"
)
# Classifications are written in batches (task F03-15): one statement per column cost a round trip
# each. Columns come from UNCLASSIFIED, so a column without an edge from this run gets a CREATE; a
# column this run already classified into the same category (dictionary, then a validator) gets
# its existing edge updated, exactly what the former per-column MERGE did.
CLASSIFY_CREATE = (
    "UNWIND $rows AS r MATCH (c:Column {key: r.key}) MATCH (k:Category {name: r.category}) "
    "CREATE (c)-[:CLASSIFIED_AS {method: r.method, confidence: r.confidence, at: $at, "
    "rate: r.rate, validated: r.validated}]->(k)"
)
CLASSIFY_UPDATE = (
    "UNWIND $rows AS r "
    "MATCH (c:Column {key: r.key})-[x:CLASSIFIED_AS]->(k:Category {name: r.category}) "
    "SET x += {method: r.method, confidence: r.confidence, at: $at, rate: r.rate, "
    "validated: r.validated}"
)


@dataclass(frozen=True, slots=True)
class ColumnRef:
    key: str
    name: str
    table: str  # schema.table


@dataclass(frozen=True, slots=True)
class ClassificationSummary:
    system_id: str
    dictionary: int
    validated: int
    probe_failures: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def unclassified_columns(store: GraphStore, system_id: str) -> list[ColumnRef]:
    rows = store.query(UNCLASSIFIED, {"sid": system_id}, ("key", "name", "table"))
    return sorted(
        (ColumnRef(str(r["key"]), str(r["name"]), str(r["table"])) for r in rows),
        key=lambda c: (c.table, c.name),
    )


def best_validation(
    column: ColumnRef, rates: dict[str, float], hints: tuple[str, ...]
) -> tuple[str, str, float] | None:
    accepted = [(rates[v], v) for v in hints if rates.get(v, 0.0) >= VALIDATOR_ACCEPT]
    if not accepted:
        return None
    rate, validator = max(accepted)
    return VALIDATOR_CATEGORY[validator], f"validator:{validator}", rate


def _edge_row(
    column: ColumnRef,
    category: str,
    method: str,
    confidence: float,
    validated: int | None = None,
) -> dict[str, Any]:
    return {
        "key": column.key,
        "category": category,
        "method": method,
        "confidence": confidence,
        "rate": confidence if validated is not None else None,
        "validated": validated,
    }


def _write_edges(
    store: GraphStore,
    rows: list[dict[str, Any]],
    written: dict[str, str],
    at: str,
) -> None:
    """Create new edges and update the ones this run already wrote, in at most two statements."""
    update = [r for r in rows if written.get(r["key"]) == r["category"]]
    create = [r for r in rows if written.get(r["key"]) != r["category"]]
    with store.connection() as conn:
        if update:
            store.execute(CLASSIFY_UPDATE, {"rows": update, "at": at}, conn)
        if create:
            store.execute(CLASSIFY_CREATE, {"rows": create, "at": at}, conn)
    written.update({r["key"]: r["category"] for r in rows})


def classify_new_columns(
    store: GraphStore,
    runner: ProbeRunner,
    system_id: str,
    available: frozenset[str] = DEFAULT_VALIDATORS,
    sample_size: int = SAMPLE_SIZE,
    now: Callable[[], datetime] = _utc_now,
) -> ClassificationSummary:
    at = now().astimezone(UTC).isoformat()
    columns = unclassified_columns(store, system_id)
    validated = failures = 0

    written: dict[str, str] = {}

    # Phase A: dictionary, free of charge; every edge in one batch.
    dictionary_rows = []
    for column in columns:
        method = "dict"
        category = match_column_name(column.name)
        if category is None:
            category = match_column_in_table(column.name, column.table)
            method = TABLE_CONTEXT_METHOD
        if category is not None:
            dictionary_rows.append(_edge_row(column, category, method, DICTIONARY_CONFIDENCE))
    if dictionary_rows:
        _write_edges(store, dictionary_rows, written, at)
    dictionary = len(dictionary_rows)

    # Phase B: one validation probe per table for the columns whose name hints a validator.
    by_table: dict[str, list[tuple[ColumnRef, tuple[str, ...]]]] = {}
    for column in columns:
        hints = validator_hints(column.name, available)
        if hints:
            by_table.setdefault(column.table, []).append((column, hints))
    for table, candidates in sorted(by_table.items()):
        names = sorted({v for _, hints in candidates for v in hints})
        params = {
            "columns": [c.name for c, _ in candidates],
            "k": sample_size,
            "validators": names,
        }
        try:
            result = runner(system_id, ProbeSpec("sample", table, params=params))
        except ValueError as refused:
            # A name the connector cannot probe stops that table, never the whole phase: it is
            # recorded and counted, and the rest of the system is still classified (SEC-024).
            _log.warning(
                "table not sampled", extra={"table": table, "error": type(refused).__name__}
            )
            failures += 1
            continue
        if not result.ok:
            failures += 1
            continue
        # The probe runs outside any transaction; its accepted columns are written together.
        accepted_rows = []
        for column, hints in candidates:
            rates = result.data.get("validator_rates", {}).get(column.name, {})
            seen = int(result.data.get("validated", {}).get(column.name, 0))
            accepted = best_validation(column, rates, hints)
            if accepted is not None:
                category, method, rate = accepted
                accepted_rows.append(_edge_row(column, category, method, rate, validated=seen))
        if accepted_rows:
            _write_edges(store, accepted_rows, written, at)
        validated += len(accepted_rows)
    return ClassificationSummary(system_id, dictionary, validated, failures)
