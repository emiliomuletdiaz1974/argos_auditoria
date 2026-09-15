"""Ingest: DISCOVERY events -> inventory graph, one transaction per event (ARG-022).

The ingest never interprets: it does not classify or infer flows, it only materialises facts with
their time and provenance. Idempotence comes from MERGE on natural keys backed by unique indexes.

AGE 1.5.0 fails with "vertex assigned to variable … was deleted" when an UNWIND batch merges nodes
and edges in the same statement after an earlier statement of the transaction updated the other
end (deviation note ARG-021-023). Batches therefore upsert nodes first and merge edges apart.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from argos_inventory.discovery.events import EventPublisher
from argos_inventory.graph.store import GraphStore

from .parameters import (
    access_parameters,
    file_area_parameters,
    summary_parameters,
    system_parameters,
    table_parameters,
)

SYSTEM_UPSERT = (
    "MERGE (s:System {key: $system_key}) SET s.id = $system_id SET s.name = $name "
    "SET s.kind = $kind SET s.owner = $owner "
    "SET s.first_seen = coalesce(s.first_seen, $at) SET s.last_seen = $at"
)
SCHEMA_UPSERT = (
    "MATCH (s:System {key: $system_key}) "
    "MERGE (h:Schema {key: $schema_key}) SET h.name = $schema SET h.system_id = $system_id "
    "SET h.first_seen = coalesce(h.first_seen, $at) SET h.last_seen = $at SET h.missing = false "
    "MERGE (s)-[:CONTAINS]->(h)"
)
TABLE_UPSERT = (
    "MATCH (h:Schema {key: $schema_key}) "
    "MERGE (t:Table {key: $table_key}) SET t.name = $table SET t.qualified_name = $qualified_name "
    "SET t.system_id = $system_id "
    "SET t.est_rows_prev = coalesce(t.est_rows, $est_rows) SET t.est_rows = $est_rows "
    "SET t.bytes = $bytes SET t.comment = $comment "
    "SET t.first_seen = coalesce(t.first_seen, $at) SET t.last_seen = $at "
    "SET t.missing = false SET t.missing_since = null "
    "SET t.source_connector = $source_connector SET t.probe_id = $probe_id "
    "SET t.journal_seq = $journal_seq "
    "MERGE (h)-[:CONTAINS]->(t)"
)
COLUMN_NODES_UPSERT = (
    "UNWIND $columns AS c "
    "MERGE (col:Column {key: c.key}) SET col.name = c.name "
    "SET col.qualified_name = c.qualified_name "
    "SET col.type = c.type SET col.nullable = c.nullable SET col.system_id = $system_id "
    "SET col.first_seen = coalesce(col.first_seen, $at) SET col.last_seen = $at "
    "SET col.missing = false SET col.missing_since = null "
    "SET col.probe_id = $probe_id SET col.journal_seq = $journal_seq"
)
COLUMN_EDGES_MERGE = (
    "UNWIND $columns AS c MATCH (t:Table {key: $table_key}) MATCH (col:Column {key: c.key}) "
    "MERGE (t)-[:CONTAINS]->(col)"
)
IDENTITIES_UPSERT = (
    "UNWIND $grants AS g "
    "MERGE (i:Identity {key: g.key}) SET i.name = g.grantee SET i.kind = 'database_role' "
    "SET i.system_id = $system_id "
    "SET i.first_seen = coalesce(i.first_seen, $at) SET i.last_seen = $at"
)
ACCESS_EDGES_UPSERT = (
    "UNWIND $grants AS g MATCH (t:Table {key: $table_key}) MATCH (i:Identity {key: g.key}) "
    "MERGE (i)-[a:CAN_ACCESS]->(t) SET a.privileges = g.privileges SET a.last_seen = $at "
    "SET a.probe_id = $probe_id"
)
FILE_AREA_UPSERT = (
    "MATCH (s:System {key: $system_key}) "
    "MERGE (f:FileArea {key: $area_key}) SET f.name = $name SET f.path = $path "
    "SET f.system_id = $system_id SET f.total = $total SET f.bytes = $bytes "
    "SET f.by_ext = $by_ext SET f.age_years = $age_years SET f.capped = $capped "
    "SET f.first_seen = coalesce(f.first_seen, $at) SET f.last_seen = $at "
    "SET f.missing = false SET f.missing_since = null "
    "SET f.probe_id = $probe_id SET f.journal_seq = $journal_seq "
    "MERGE (s)-[:CONTAINS]->(f)"
)
SUMMARY_SET = (
    "MATCH (s:System {key: $system_key}) SET s.summary = $summary "
    "SET s.summary_kind = $summary_kind SET s.routes = $routes SET s.summary_probe_id = $probe_id"
)
SYSTEM_TOUCH = (
    "MERGE (s:System {key: $system_key}) SET s.id = $system_id SET s.name = $name "
    "SET s.kind = $kind SET s.owner = $owner "
    "SET s.first_seen = coalesce(s.first_seen, $at)"
)
SCAN_COMPLETED_SET = (
    "MATCH (s:System {key: $system_key}) SET s.last_scan_run = $run_id "
    "SET s.last_scan_status = $status SET s.last_scan_at = $finished_at"
)


@dataclass(frozen=True, slots=True)
class SystemMeta:
    id: str
    name: str
    kind: str
    owner: str | None


Handler = Callable[[GraphStore, str, dict[str, Any], SystemMeta], None]


def load_system_meta(dsn: str, system_id: str) -> SystemMeta:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT id::text, name, kind, owner FROM argos.systems WHERE id = %s", (system_id,)
        ).fetchone()
    if row is None:
        raise LookupError(f"unknown system: {system_id}")
    return SystemMeta(str(row[0]), str(row[1]), str(row[2]), row[3])


def ingest_table_found(
    store: GraphStore, event_type: str, data: dict[str, Any], meta: SystemMeta
) -> None:
    params = table_parameters(data)
    with store.connection() as conn:
        store.execute(SYSTEM_UPSERT, system_parameters(meta, params["at"]), conn)
        store.execute(SCHEMA_UPSERT, params, conn)
        store.execute(TABLE_UPSERT, params, conn)
        store.execute(COLUMN_NODES_UPSERT, params, conn)
        store.execute(COLUMN_EDGES_MERGE, params, conn)


def ingest_access_found(
    store: GraphStore, event_type: str, data: dict[str, Any], meta: SystemMeta
) -> None:
    params = access_parameters(data)
    with store.connection() as conn:
        store.execute(IDENTITIES_UPSERT, params, conn)
        store.execute(ACCESS_EDGES_UPSERT, params, conn)


def ingest_file_area(
    store: GraphStore, event_type: str, data: dict[str, Any], meta: SystemMeta
) -> None:
    params = file_area_parameters(data)
    with store.connection() as conn:
        store.execute(SYSTEM_UPSERT, system_parameters(meta, params["at"]), conn)
        store.execute(FILE_AREA_UPSERT, params, conn)


def ingest_summary(
    store: GraphStore, event_type: str, data: dict[str, Any], meta: SystemMeta
) -> None:
    with store.connection() as conn:
        store.execute(SYSTEM_UPSERT, system_parameters(meta, str(data["observed_at"])), conn)
        store.execute(SUMMARY_SET, summary_parameters(event_type, data), conn)


def ingest_scan_completed(
    store: GraphStore, event_type: str, data: dict[str, Any], meta: SystemMeta
) -> None:
    at = str(data["finished_at"])
    params = {**system_parameters(meta, at), **{k: data[k] for k in ("run_id", "status")}}
    params["finished_at"] = at
    with store.connection() as conn:
        store.execute(SYSTEM_TOUCH, params, conn)
        store.execute(SCAN_COMPLETED_SET, params, conn)


HANDLERS: dict[str, Handler] = {
    "discovery.table_found.v1": ingest_table_found,
    "discovery.access_found.v1": ingest_access_found,
    "discovery.file_area_scanned.v1": ingest_file_area,
    "discovery.directory_summarized.v1": ingest_summary,
    "discovery.api_routes_found.v1": ingest_summary,
    "discovery.clinical_resources_found.v1": ingest_summary,
    "discovery.scan_completed.v1": ingest_scan_completed,
}


class Ingestor:
    def __init__(self, store: GraphStore, dsn: str, bus: EventPublisher) -> None:
        self.store = store
        self._dsn = dsn
        self._bus = bus
        self._meta: dict[str, SystemMeta] = {}

    async def _system(self, system_id: str) -> SystemMeta:
        if system_id not in self._meta:
            self._meta[system_id] = await asyncio.to_thread(load_system_meta, self._dsn, system_id)
        return self._meta[system_id]

    async def handle(self, data: dict[str, Any], event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "")).removeprefix("eu.argos.")
        handler = HANDLERS.get(event_type)
        if handler is None:
            return  # own events (ingested, delta_ready) and future types pass through
        meta = await self._system(str(data["system_id"]))
        await asyncio.to_thread(handler, self.store, event_type, data, meta)
        if event_type == "discovery.scan_completed.v1":
            ingested = {"system_id": meta.id, "run_id": data["run_id"], "status": data["status"]}
            await self._bus.publish("argos.discovery.ingested", "discovery.ingested.v1", ingested)
