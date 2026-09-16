"""Discovery of AI in use: weak read-only signals, accumulation and human confirmation (ARG-028).

ARGOS is not a sniffer: signals come from what the connectors already saw (API routes, model files,
score-like columns). A candidate is never confirmed by signals alone; the DPO confirms it and fills
the AI Act fields (deviation note ARG-026-028).
"""

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Self

from argos_common.journal_pg import PostgresJournal
from argos_inventory.classify.dictionary import name_tokens
from argos_inventory.graph.model import ai_system_key, system_key
from argos_inventory.graph.store import GraphStore

AI_ROUTES = re.compile(
    r"/(predict|inference|score|v1/(chat|completions)|embeddings|classify)(/|$|\?)", re.I
)
MODEL_EXTENSIONS = frozenset({"onnx", "pt", "pth", "safetensors", "pkl", "h5", "gguf"})
SCORE_TOKENS = frozenset({"score", "pred", "prediction", "probability", "propensity", "propension"})
ROUTE_CONFIDENCE = 0.5
MODEL_FILE_CONFIDENCE = 0.4
SCORE_COLUMN_CONFIDENCE = 0.3
PROVISIONAL_THRESHOLD = 0.5
RISK_CLASSES = frozenset({"prohibited", "high", "limited", "minimal"})

_CURRENT_SIGNALS = "MATCH (a:AISystem {key: $key}) RETURN a.signals"
_UPSERT = (
    "MATCH (s:System {key: $system_key}) "
    "MERGE (a:AISystem {key: $key}) SET a.name = $name SET a.system_id = $system_id "
    "SET a.signals = $signals SET a.confidence = $confidence "
    "SET a.status = coalesce(a.status, 'pending') SET a.last_seen = $at "
    "MERGE (s)-[:USES_MODEL]->(a)"
)
_ROUTES = "MATCH (s:System) WHERE s.routes IS NOT NULL RETURN s.id, s.routes"
_FILE_AREAS = (
    "MATCH (s:System)-[:CONTAINS]->(f:FileArea) WHERE f.by_ext IS NOT NULL RETURN s.id, f.by_ext"
)
_COLUMNS = (
    "MATCH (s:System)-[:CONTAINS*2]->(t:Table)-[:CONTAINS]->(c:Column) "
    "WHERE coalesce(c.missing, false) = false RETURN s.id, t.name, c.name"
)
_REGISTER = (
    "MATCH (s:System)-[:USES_MODEL]->(a:AISystem) "
    "WHERE a.confidence >= $threshold OR a.status = 'confirmed' "
    "RETURN s.id, a.key, a.name, a.confidence, a.status"
)
_CONFIRM = (
    "MATCH (a:AISystem {key: $key}) SET a.status = 'confirmed' SET a.purpose = $purpose "
    "SET a.risk_class = $risk_class SET a.confirmed_by = $reviewer SET a.confirmed_at = $at "
    "RETURN a.key"
)


@dataclass(frozen=True, slots=True)
class Signal:
    kind: str
    confidence: float
    detail: str

    def encode(self) -> str:
        return f"{self.kind}|{self.confidence}|{self.detail[:120]}"

    @classmethod
    def decode(cls, text: str) -> Self:
        kind, confidence, detail = text.split("|", 2)
        return cls(kind, float(confidence), detail)


@dataclass(frozen=True, slots=True)
class AiDiscoverySummary:
    routes: int
    files: int
    columns: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def aggregate_confidence(confidences: Iterable[float]) -> float:
    values = list(confidences)
    if not values:
        return 0.0
    return round(1 - math.prod(1 - min(max(c, 0.0), 1.0) for c in values), 4)


def is_ai_route(path: str) -> bool:
    return AI_ROUTES.search(path) is not None


def is_score_column(name: str) -> bool:
    return any(token in SCORE_TOKENS for token in name_tokens(name))


def record_signal(store: GraphStore, system_id: str, name: str, signal: Signal, at: str) -> float:
    key = ai_system_key(system_id, name)
    with store.connection() as conn:
        rows = store.query(_CURRENT_SIGNALS, {"key": key}, ("signals",), conn)
        current = list(rows[0]["signals"] or []) if rows else []
        encoded = signal.encode()
        if encoded not in current:
            current.append(encoded)
        confidence = aggregate_confidence(Signal.decode(s).confidence for s in current)
        params: dict[str, Any] = {
            "system_key": system_key(system_id),
            "system_id": system_id,
            "key": key,
            "name": name,
            "signals": sorted(current),
            "confidence": confidence,
            "at": at,
        }
        store.execute(_UPSERT, params, conn)
    return confidence


def detect_from_routes(store: GraphStore, now: Callable[[], datetime] = _utc_now) -> int:
    at = now().astimezone(UTC).isoformat()
    found = 0
    for row in store.query(_ROUTES, columns=("system", "routes")):
        for route in row["routes"] or []:
            if is_ai_route(str(route)):
                signal = Signal("route", ROUTE_CONFIDENCE, str(route))
                record_signal(store, str(row["system"]), f"api:{route}", signal, at)
                found += 1
    return found


def detect_from_files(store: GraphStore, now: Callable[[], datetime] = _utc_now) -> int:
    at = now().astimezone(UTC).isoformat()
    found = 0
    for row in store.query(_FILE_AREAS, columns=("system", "by_ext")):
        for extension in sorted((row["by_ext"] or {}).keys()):
            name = str(extension).lower()
            if name in MODEL_EXTENSIONS:
                signal = Signal("model_file", MODEL_FILE_CONFIDENCE, name)
                record_signal(store, str(row["system"]), f"files:*.{name}", signal, at)
                found += 1
    return found


def detect_from_columns(store: GraphStore, now: Callable[[], datetime] = _utc_now) -> int:
    at = now().astimezone(UTC).isoformat()
    tables: set[tuple[str, str]] = set()
    for row in store.query(_COLUMNS, columns=("system", "table", "column")):
        if is_score_column(str(row["column"])):
            tables.add((str(row["system"]), str(row["table"])))
    for system_id, table in sorted(tables):
        signal = Signal("score_column", SCORE_COLUMN_CONFIDENCE, table)
        record_signal(store, system_id, f"table:{table}", signal, at)
    return len(tables)


def discover_ai(store: GraphStore, now: Callable[[], datetime] = _utc_now) -> AiDiscoverySummary:
    return AiDiscoverySummary(
        routes=detect_from_routes(store, now),
        files=detect_from_files(store, now),
        columns=detect_from_columns(store, now),
    )


def provisional_register(store: GraphStore) -> list[dict[str, Any]]:
    rows = store.query(
        _REGISTER,
        {"threshold": PROVISIONAL_THRESHOLD},
        ("system", "key", "name", "confidence", "status"),
    )
    return sorted(rows, key=lambda r: (-float(r["confidence"]), str(r["name"])))


def confirm_ai_system(
    store: GraphStore,
    dsn: str,
    key: str,
    reviewer: str,
    purpose: str,
    risk_class: str,
    now: Callable[[], datetime] = _utc_now,
) -> None:
    if not reviewer.startswith("user:"):
        raise ValueError(
            "AI systems are confirmed by a person: reviewer must be a user:<sub> actor"
        )
    if risk_class not in RISK_CLASSES:
        raise ValueError(f"unknown AI Act risk class: {risk_class!r}")
    at = now().astimezone(UTC).isoformat()
    journal = PostgresJournal(dsn)
    with store.connection() as conn:
        params = {
            "key": key,
            "purpose": purpose,
            "risk_class": risk_class,
            "reviewer": reviewer,
            "at": at,
        }
        if not store.query(_CONFIRM, params, ("key",), conn):
            raise LookupError(f"unknown AI system candidate: {key}")
        payload = {"key": key, "purpose": purpose, "risk_class": risk_class}
        journal.append(reviewer, "inventory.ai_confirm", payload, conn=conn)
