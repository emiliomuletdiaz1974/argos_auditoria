"""Import of the DPO record of processing activities into the inventory graph (ARG-026).

The CSV is validated completely before anything is written; declarations that disappear from the
file are removed, and every import leaves a journal entry (deviation note ARG-026-028).
"""

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from argos_common.journal_pg import PostgresJournal
from argos_inventory.graph.model import system_key, treatment_key
from argos_inventory.graph.store import GraphStore

TREATMENT_HEADERS = ("id", "name", "legal_basis", "retention", "systems")

_TREATMENT_UPSERT = (
    "MERGE (tr:Treatment {key: $key}) SET tr.id = $id SET tr.name = $name "
    "SET tr.legal_basis = $legal_basis SET tr.retention = $retention SET tr.imported_at = $at"
)
_STALE_DECLARATIONS = (
    "MATCH (s:System)-[d:DECLARED_IN]->(tr:Treatment {key: $key}) "
    "WHERE NOT s.id IN $system_ids RETURN s.id"
)
_REMOVE_DECLARATIONS = (
    "MATCH (s:System)-[d:DECLARED_IN]->(tr:Treatment {key: $key}) "
    "WHERE NOT s.id IN $system_ids DELETE d"
)
_SYSTEM_UPSERT = "MERGE (s:System {key: $system_key}) SET s.id = $system_id"
_DECLARE = (
    "MATCH (s:System {key: $system_key}), (tr:Treatment {key: $key}) "
    "MERGE (s)-[d:DECLARED_IN]->(tr) SET d.at = $at"
)


@dataclass(frozen=True, slots=True)
class TreatmentRow:
    id: str
    name: str
    legal_basis: str
    retention: str
    systems: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImportSummary:
    treatments: int
    links: int
    removed: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def parse_treatments(csv_bytes: bytes) -> list[TreatmentRow]:
    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if tuple(reader.fieldnames or ()) != TREATMENT_HEADERS:
        raise ValueError(f"unexpected headers: expected {';'.join(TREATMENT_HEADERS)}")
    rows: list[TreatmentRow] = []
    seen: set[str] = set()
    for line, record in enumerate(reader, start=2):
        treatment_id = (record["id"] or "").strip()
        if not treatment_id:
            raise ValueError(f"empty id at line {line}")
        if treatment_id in seen:
            raise ValueError(f"duplicate treatment id {treatment_id!r} at line {line}")
        seen.add(treatment_id)
        systems = tuple(s.strip() for s in (record["systems"] or "").split(",") if s.strip())
        rows.append(
            TreatmentRow(
                treatment_id,
                (record["name"] or "").strip(),
                (record["legal_basis"] or "").strip(),
                (record["retention"] or "").strip(),
                systems,
            )
        )
    return rows


def _resolve_systems(dsn: str, rows: list[TreatmentRow]) -> dict[str, str]:
    with psycopg.connect(dsn) as conn:
        registered = conn.execute("SELECT id::text, name FROM argos.systems").fetchall()
    by_reference = {str(i): str(i) for i, _ in registered}
    by_reference |= {str(n): str(i) for i, n in registered}
    wanted = {reference for row in rows for reference in row.systems}
    unknown = sorted(wanted - set(by_reference))
    if unknown:
        raise ValueError(f"unknown systems in treatments: {unknown}")
    return {reference: by_reference[reference] for reference in wanted}


def import_treatments(
    store: GraphStore,
    dsn: str,
    csv_bytes: bytes,
    actor: str,
    now: Callable[[], datetime] = _utc_now,
) -> ImportSummary:
    if not actor.startswith("user:"):
        raise ValueError("the record of processing activities is imported by a person (user:<sub>)")
    rows = parse_treatments(csv_bytes)
    resolved = _resolve_systems(dsn, rows)
    at = now().astimezone(UTC).isoformat()
    links = removed = 0
    journal = PostgresJournal(dsn)
    with store.connection() as conn:
        for row in rows:
            key = treatment_key(row.id)
            system_ids = sorted({resolved[reference] for reference in row.systems})
            treatment = {
                "key": key,
                "id": row.id,
                "name": row.name,
                "legal_basis": row.legal_basis,
                "retention": row.retention,
                "at": at,
            }
            store.execute(_TREATMENT_UPSERT, treatment, conn)
            scope = {"key": key, "system_ids": system_ids}
            stale = store.query(_STALE_DECLARATIONS, scope, ("id",), conn)
            if stale:
                store.execute(_REMOVE_DECLARATIONS, scope, conn)
                removed += len(stale)
            for system_id in system_ids:
                node = {"system_key": system_key(system_id), "system_id": system_id}
                store.execute(_SYSTEM_UPSERT, node, conn)
                declaration = {"system_key": system_key(system_id), "key": key, "at": at}
                store.execute(_DECLARE, declaration, conn)
                links += 1
        payload = {"treatments": len(rows), "links": links, "removed": removed}
        journal.append(actor, "inventory.treatments_import", payload, conn=conn)
    return ImportSummary(len(rows), links, removed)
