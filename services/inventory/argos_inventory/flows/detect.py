"""Flow detection between systems: engine catalog links and structural matching (ARG-027).

Read-only sources ordered by reliability. Every FLOWS_TO edge carries its method and confidence and
one edge exists per (source, target, method); an inferred flow is never presented as confirmed,
and only the DPO sets `confirmed` (deviation note ARG-026-028).
"""

import itertools
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from argos_connector.probes import ProbeResult, ProbeSpec
from argos_inventory.discovery.probes import connector_class, load_system
from argos_inventory.graph.model import natural_key, system_key
from argos_inventory.graph.store import GraphStore

ENGINE_LINK_SQL: Mapping[str, str] = {
    "rdbms.postgresql": "SELECT srvname AS name, srvoptions AS options FROM pg_foreign_server",
    "rdbms.mssql": "SELECT name, data_source AS options FROM sys.servers WHERE is_linked = 1",
}
ENGINE_LINK_CONFIDENCE = 0.95
STRUCTURAL_MIN_PAIRS = 4
STRUCTURAL_MIN_JACCARD = 0.8
STRUCTURAL_MAX_CONFIDENCE = 0.6
MAX_EVIDENCE = 500

ProbeRunner = Callable[[str, ProbeSpec], ProbeResult]

_PG_HOST = re.compile(r"(?:^|[\s,'\"{\[])host=([A-Za-z0-9._-]+)")
_SIGNATURES = (
    "MATCH (s:System)-[:CONTAINS*2]->(t:Table)-[:CONTAINS]->(c:Column)"
    "-[:CLASSIFIED_AS]->(k:Category) WHERE coalesce(c.missing, false) = false "
    "RETURN s.id, t.qualified_name, c.name, k.name"
)
_SOURCE = "MATCH (a:System {key: $source_key}) SET a.id = $source_id"
_TARGET_INTERNAL = "MERGE (b:System {key: $target_key}) SET b.id = $target_id"
_TARGET_EXTERNAL = (
    "MERGE (b:System {key: $target_key}) SET b.external = true SET b.name = $target_name"
)
_FLOW = (
    "MATCH (a:System {key: $source_key}), (b:System {key: $target_key}) "
    "MERGE (a)-[f:FLOWS_TO {method: $method}]->(b) SET f.confidence = $confidence "
    "SET f.evidence = $evidence SET f.last_seen = $at "
    "SET f.confirmed = coalesce(f.confirmed, false)"
)


@dataclass(frozen=True, slots=True)
class FlowTarget:
    system_id: str | None
    key: str
    name: str
    external: bool


@dataclass(frozen=True, slots=True)
class FlowSummary:
    system_id: str
    engine_links: int
    structural: int
    probe_failures: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def link_host(options: object) -> str | None:
    """Host of a declared link: PostgreSQL srvoptions (list or text) or a SQL Server data_source."""
    if options is None:
        return None
    text = str(options)
    match = _PG_HOST.search(text)
    if match:
        return match.group(1)
    if "=" in text:
        return None
    host = re.split(r"[,\\:]", text.strip(), maxsplit=1)[0].strip()
    return host or None


def jaccard(a: set[str] | frozenset[str], b: set[str] | frozenset[str]) -> float:
    union = a | b
    return round(len(a & b) / len(union), 4) if union else 0.0


def structural_candidates(
    signatures: Mapping[tuple[str, str], frozenset[str]],
) -> list[tuple[tuple[str, str], tuple[str, str], float]]:
    """Pairs of tables of different systems with the same classified signature.

    Blocking: only tables with enough classified columns are compared, and only inside the groups
    of a shared special category, so the whole estate is never compared pair by pair.
    """
    blocks: dict[str, list[tuple[str, str]]] = {}
    for table, signature in signatures.items():
        if len(signature) < STRUCTURAL_MIN_PAIRS:
            continue
        for pair in signature:
            category = pair.split("|", 1)[1]
            if category.startswith("special_category."):
                blocks.setdefault(category, []).append(table)
    seen: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    candidates: list[tuple[tuple[str, str], tuple[str, str], float]] = []
    for tables in blocks.values():
        for a, b in itertools.combinations(sorted(set(tables)), 2):
            if a[0] == b[0] or (a, b) in seen:
                continue
            seen.add((a, b))
            score = jaccard(signatures[a], signatures[b])
            if score >= STRUCTURAL_MIN_JACCARD:
                candidates.append((a, b, score))
    return candidates


def resolve_target(dsn: str, host: str | None, link_name: str) -> FlowTarget:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT id::text, name, connection FROM argos.systems").fetchall()
    for system_id, name, connection in rows:
        config = (connection or {}).get("config", {})
        aliases = {str(a).lower() for a in config.get("host_aliases", [])}
        if (host and host.lower() in aliases) or link_name == name or (host and host == name):
            return FlowTarget(str(system_id), system_key(str(system_id)), str(name), False)
    reference = host or link_name
    return FlowTarget(None, natural_key("X", reference.lower()), reference, True)


def emit_flow(
    store: GraphStore,
    source_system_id: str,
    target: FlowTarget,
    method: str,
    confidence: float,
    evidence: str,
    at: str,
) -> None:
    params = {
        "source_key": system_key(source_system_id),
        "source_id": source_system_id,
        "target_key": target.key,
        "target_id": target.system_id,
        "target_name": target.name,
        "method": method,
        "confidence": confidence,
        "evidence": evidence[:MAX_EVIDENCE],
        "at": at,
    }
    with store.connection() as conn:
        store.execute(_SOURCE, params, conn)
        store.execute(_TARGET_EXTERNAL if target.external else _TARGET_INTERNAL, params, conn)
        store.execute(_FLOW, params, conn)


def detect_engine_links(
    store: GraphStore,
    dsn: str,
    runner: ProbeRunner,
    system_id: str,
    now: Callable[[], datetime] = _utc_now,
) -> FlowSummary:
    system = load_system(dsn, system_id)
    kind = str(getattr(connector_class(system.connector), "kind", ""))
    statement = ENGINE_LINK_SQL.get(kind)
    if statement is None:
        return FlowSummary(system_id, 0, 0, 0)
    result = runner(system_id, ProbeSpec("check_config", "engine_links", statement=statement))
    if not result.ok:
        return FlowSummary(system_id, 0, 0, 1)
    at = now().astimezone(UTC).isoformat()
    links = 0
    for row in result.data.get("rows", []):
        name = str(row.get("name", ""))
        host = link_host(row.get("options"))
        target = resolve_target(dsn, host, name)
        if target.system_id == system_id:
            continue
        evidence = json.dumps({"link": name, "host": host}, ensure_ascii=False)
        emit_flow(store, system_id, target, "engine_catalog", ENGINE_LINK_CONFIDENCE, evidence, at)
        links += 1
    return FlowSummary(system_id, links, 0, 0)


def detect_structural(store: GraphStore, now: Callable[[], datetime] = _utc_now) -> int:
    signatures: dict[tuple[str, str], set[str]] = {}
    for row in store.query(_SIGNATURES, columns=("system", "table", "column", "category")):
        table = (str(row["system"]), str(row["table"]))
        signatures.setdefault(table, set()).add(f"{row['column']}|{row['category']}")
    frozen = {table: frozenset(pairs) for table, pairs in signatures.items()}
    at = now().astimezone(UTC).isoformat()
    emitted: set[frozenset[str]] = set()
    for a, b, score in structural_candidates(frozen):
        systems = frozenset({a[0], b[0]})
        if systems in emitted:
            continue  # one structural flow per pair of systems; the evidence names the tables
        emitted.add(systems)
        source, target_id = sorted(systems)
        target = FlowTarget(target_id, system_key(target_id), target_id, False)
        evidence = json.dumps({"tables": sorted([a[1], b[1]]), "jaccard": score})
        confidence = round(min(score * STRUCTURAL_MAX_CONFIDENCE, STRUCTURAL_MAX_CONFIDENCE), 2)
        emit_flow(store, source, target, "structural", confidence, evidence, at)
    return len(emitted)
