"""Applicability resolver: (ontology in force x today's graph) -> applicability plan (ARG-039).

It answers the question that starts every campaign: which obligations apply to which assets, and
with which challenges are they verified. Every plan row keeps its why (obligation, asset class,
selector, challenge, resolved nodes) and the run keeps the ontology version, so the file handed to
a supervisor starts here. Selectors are resolved through a protocol: in process today, over the
inventory API with a service token when one exists (deviation note ARG-034-040).
"""

import asyncio
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb
from rdflib import Graph
from rdflib.query import ResultRow

from argos_common.ids import uuid7
from argos_common.journal_pg import PostgresJournal
from argos_inventory.api.pagination import MAX_PAGE_SIZE
from argos_inventory.api.selector import NODE_COLUMNS, Selector, compile_selector, parse_selector
from argos_inventory.discovery.events import EventPublisher
from argos_inventory.graph.store import GraphStore
from argos_ontology.store import OntologyStore
from argos_ontology.vocabulary import bind_prefixes

JOURNAL_ACTOR = "system:resolver"
JOURNAL_ACTION = "applicability.resolve"
EVENT_SUBJECT = "argos.challenge.applicability_ready"
EVENT_TYPE = "challenge.applicability_ready.v1"
SCOPE_FIELDS = frozenset({"system_ids"})

REQUIREMENTS = """
SELECT ?obligation ?label ?severity ?asset_class ?selector ?pending ?challenge_id
       ?in_force_from ?in_force_until WHERE {
  ?obligation a argos:Obligation ;
              rdfs:label ?label ;
              argos:severity ?severity ;
              argos:appliesTo ?asset_class ;
              argos:verifiedBy ?challenge .
  ?challenge argos:challengeId ?challenge_id .
  OPTIONAL { ?asset_class argos:selectorJson ?selector }
  OPTIONAL { ?asset_class argos:verificationPending ?pending }
  OPTIONAL { ?obligation argos:inForceFrom ?in_force_from }
  OPTIONAL { ?obligation argos:inForceUntil ?in_force_until }
}
"""
_SYSTEMS_OF_KIND = "MATCH (s:System {kind: $kind}) RETURN s.id"
_INSERT_RUN = (
    "INSERT INTO argos.applicability_runs "
    "(id, campaign_id, ontology_version, resolved_for, scope, plan, skipped, pairs, nodes_total) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


@dataclass(frozen=True, slots=True, order=True)
class ResolvedNode:
    key: str
    system_id: str | None


class SelectorResolver(Protocol):
    def resolve(self, selector: Selector) -> list[ResolvedNode]: ...


class StoreSelectorResolver:
    """Resolves selectors in process with the compiler, guards and pages of the inventory API."""

    def __init__(self, store: GraphStore, page_size: int = MAX_PAGE_SIZE) -> None:
        self._store = store
        self._page_size = page_size

    def resolve(self, selector: Selector) -> list[ResolvedNode]:
        nodes: list[ResolvedNode] = []
        after: str | None = None
        with self._store.connection() as conn:
            system_ids = None
            if selector.system_kind is not None:
                rows = self._store.query(
                    _SYSTEMS_OF_KIND, {"kind": selector.system_kind}, ("id",), conn
                )
                system_ids = [str(row["id"]) for row in rows]
            while True:
                cypher, params = compile_selector(selector, self._page_size, after, system_ids)
                page = self._store.query(cypher, params, NODE_COLUMNS, conn)
                for row in page[: self._page_size]:
                    system = row["system_id"]
                    nodes.append(
                        ResolvedNode(str(row["key"]), None if system is None else str(system))
                    )
                if len(page) <= self._page_size:
                    return nodes
                after = nodes[-1].key


@dataclass(frozen=True, slots=True)
class Requirement:
    obligation: str
    label: str
    severity: str
    asset_class: str
    selector: dict[str, Any] | None
    verification_pending: str | None
    challenge_id: str


@dataclass(frozen=True, slots=True)
class ApplicabilityRun:
    run_id: str
    ontology_version: str
    resolved_for: date
    pairs: int
    nodes_total: int
    plan: list[dict[str, Any]]
    skipped: list[dict[str, str]]


def _selector_json(raw: object) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(str(raw))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _date(value: object) -> date | None:
    python = value.toPython() if hasattr(value, "toPython") else value
    return python if isinstance(python, date) else None


def in_force(at: date | None, start: object, end: object) -> bool:
    """An obligation applies from its inForceFrom and until (excluded) its inForceUntil."""
    if at is None:
        return True
    since, until = _date(start), _date(end)
    return (since is None or since <= at) and (until is None or at < until)


def requirements(ontology: Graph, at: date | None = None) -> list[Requirement]:
    """(obligation, asset class, challenge) triples in force on `at` (all when None), sorted;
    obligations without challenges are left to the traceability matrix."""
    found: dict[tuple[str, str, str], Requirement] = {}
    for row in bind_prefixes(ontology).query(REQUIREMENTS):
        if not isinstance(row, ResultRow):  # pragma: no cover - SELECT always yields rows
            continue
        obligation, label, severity, asset_class, selector, pending, challenge_id, since, until = (
            row
        )
        if not in_force(at, since, until):
            continue
        requirement = Requirement(
            obligation=str(obligation),
            label=str(label),
            severity=str(severity),
            asset_class=str(asset_class),
            selector=_selector_json(selector),
            verification_pending=None if pending is None else str(pending),
            challenge_id=str(challenge_id),
        )
        found[(requirement.obligation, requirement.asset_class, requirement.challenge_id)] = (
            requirement
        )
    return [found[key] for key in sorted(found)]


def check_scope(scope: Mapping[str, Any]) -> dict[str, Any]:
    """Only `system_ids` (a non-empty list of texts) narrows a run; the result is normalised."""
    unknown = set(scope) - SCOPE_FIELDS
    if unknown:
        raise ValueError(f"scope fields not allowed: {sorted(unknown)}")
    if "system_ids" not in scope:
        return {}
    ids = scope["system_ids"]
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
        raise ValueError("scope system_ids must be a non-empty list of texts")
    return {"system_ids": sorted(set(ids))}


def _skip(requirement: Requirement, reason: str) -> dict[str, str]:
    return {
        "obligation": requirement.obligation,
        "asset_class": requirement.asset_class,
        "challenge_id": requirement.challenge_id,
        "reason": reason,
    }


def build_plan(
    found: Iterable[Requirement], selectors: SelectorResolver, scope: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Plan rows with nodes in scope, and the requirements that could not be resolved, with why."""
    allowed = check_scope(scope).get("system_ids")
    cache: dict[Selector, list[ResolvedNode]] = {}
    plan: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for requirement in found:
        if requirement.selector is None:
            pending = requirement.verification_pending
            reason = "asset class without selector" + (f": {pending}" if pending else "")
            skipped.append(_skip(requirement, reason))
            continue
        try:
            selector = parse_selector(requirement.selector)
        except ValueError as exc:
            skipped.append(_skip(requirement, f"invalid selector: {exc}"))
            continue
        if selector not in cache:
            cache[selector] = selectors.resolve(selector)
        keys = sorted({n.key for n in cache[selector] if allowed is None or n.system_id in allowed})
        if not keys:
            continue
        plan.append(
            {
                "obligation": requirement.obligation,
                "label": requirement.label,
                "severity": requirement.severity,
                "asset_class": requirement.asset_class,
                "selector": requirement.selector,
                "challenge_id": requirement.challenge_id,
                "node_keys": keys,
            }
        )
    return plan, skipped


def resolve(
    dsn: str,
    ontology: OntologyStore,
    selectors: SelectorResolver,
    scope: Mapping[str, Any],
    campaign_id: str | None = None,
    bus: EventPublisher | None = None,
    at: date | None = None,
) -> ApplicabilityRun:
    """Resolve for a date (today by default), persist the run with its journal entry in one
    transaction, then announce it."""
    normalised = check_scope(scope)
    campaign = None if campaign_id is None else uuid.UUID(campaign_id)
    moment = at or datetime.now(UTC).date()
    plan, skipped = build_plan(requirements(ontology.graph, moment), selectors, normalised)
    run = ApplicabilityRun(
        run_id=str(uuid7()),
        ontology_version=ontology.version,
        resolved_for=moment,
        pairs=len(plan),
        nodes_total=sum(len(row["node_keys"]) for row in plan),
        plan=plan,
        skipped=skipped,
    )
    with psycopg.connect(dsn) as conn:
        conn.execute(
            _INSERT_RUN,
            (
                run.run_id,
                campaign,
                run.ontology_version,
                run.resolved_for,
                Jsonb(normalised),
                Jsonb(plan),
                Jsonb(skipped),
                run.pairs,
                run.nodes_total,
            ),
        )
        payload = {
            "run": run.run_id,
            "ontology": run.ontology_version,
            "at": run.resolved_for.isoformat(),
            "pairs": run.pairs,
            "nodes": run.nodes_total,
        }
        PostgresJournal(dsn).append(JOURNAL_ACTOR, JOURNAL_ACTION, payload, conn=conn)
    if bus is not None:
        ready = {
            "run_id": run.run_id,
            "campaign_id": campaign_id,
            "ontology": run.ontology_version,
            "pairs": run.pairs,
        }
        asyncio.run(bus.publish(EVENT_SUBJECT, EVENT_TYPE, ready))
    return run
