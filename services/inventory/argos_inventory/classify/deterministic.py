"""Deterministic classification: name dictionary first, validation in origin second (ARG-024).

A validator with a high acceptance rate wins over the dictionary; the dictionary wins over nothing.
Only acceptance rates ever leave the connector (deviation note ARG-024-025).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from argos_connector.probes import ProbeResult, ProbeSpec
from argos_inventory.graph.store import GraphStore

from .dictionary import (
    DEFAULT_VALIDATORS,
    VALIDATOR_CATEGORY,
    match_column_name,
    validator_hints,
)

DICTIONARY_CONFIDENCE = 0.6
VALIDATOR_ACCEPT = 0.9
SAMPLE_SIZE = 200

ProbeRunner = Callable[[str, ProbeSpec], ProbeResult]

_UNCLASSIFIED = (
    "MATCH (:System {id: $sid})-[:CONTAINS*2]->(t:Table)-[:CONTAINS]->(c:Column) "
    "WHERE NOT exists((c)-[:CLASSIFIED_AS]->()) AND coalesce(c.missing, false) = false "
    "RETURN c.key, c.name, t.qualified_name"
)
_CLASSIFY = (
    "MATCH (c:Column {key: $key}), (k:Category {name: $category}) "
    "MERGE (c)-[r:CLASSIFIED_AS]->(k) SET r.method = $method SET r.confidence = $confidence "
    "SET r.at = $at SET r.rate = $rate SET r.validated = $validated"
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
    rows = store.query(_UNCLASSIFIED, {"sid": system_id}, ("key", "name", "table"))
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


def _write(
    store: GraphStore,
    column: ColumnRef,
    category: str,
    method: str,
    confidence: float,
    at: str,
    validated: int | None = None,
) -> None:
    params = {
        "key": column.key,
        "category": category,
        "method": method,
        "confidence": confidence,
        "at": at,
        "rate": confidence if validated is not None else None,
        "validated": validated,
    }
    store.execute(_CLASSIFY, params)


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
    dictionary = validated = failures = 0

    # Phase A: dictionary, free of charge.
    for column in columns:
        category = match_column_name(column.name)
        if category is not None:
            _write(store, column, category, "dict", DICTIONARY_CONFIDENCE, at)
            dictionary += 1

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
        result = runner(system_id, ProbeSpec("sample", table, params=params))
        if not result.ok:
            failures += 1
            continue
        for column, hints in candidates:
            rates = result.data.get("validator_rates", {}).get(column.name, {})
            seen = int(result.data.get("validated", {}).get(column.name, 0))
            accepted = best_validation(column, rates, hints)
            if accepted is not None:
                category, method, rate = accepted
                _write(store, column, category, method, rate, at, validated=seen)
                validated += 1
    return ClassificationSummary(system_id, dictionary, validated, failures)
