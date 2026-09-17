"""ARG-039 · resolving the ontology against a scanned inventory leaves a run and an event."""

import uuid
from datetime import date
from typing import Any

import psycopg
import pytest
from rdflib import RDF, RDFS, Graph, Literal

from argos_inventory.api.selector import NODE_COLUMNS, compile_selector, parse_selector
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore
from argos_ontology.applicability import load_asset_classes
from argos_ontology.resolver import (
    EVENT_SUBJECT,
    EVENT_TYPE,
    StoreSelectorResolver,
    resolve,
)
from argos_ontology.store import OntologyStore, store_version
from argos_ontology.vocabulary import ARGOS, NORMS, bind_prefixes
from integration.inventory_helpers import probe_runner, scan_and_ingest

pytestmark = pytest.mark.integration

HASH = "b" * 64
CAMPAIGN = "0192b000-0000-7000-8000-00000000ca01"


class RecordingBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(
        self, subject: str, event_type: str, data: dict[str, Any], audit: bool = False
    ) -> int:
        self.published.append((subject, event_type, data))
        return len(self.published)


def _ontology() -> Graph:
    graph = bind_prefixes(Graph()) + load_asset_classes()
    node = NORMS["OBL-TEST-HEALTH-RETENTION"]
    graph.add((node, RDF.type, ARGOS.Obligation))
    graph.add((node, RDFS.label, Literal("Conservación de datos de salud", lang="es")))
    graph.add((node, ARGOS.severity, Literal("high")))
    graph.add((node, ARGOS.appliesTo, NORMS["AC-stored-health-data"]))
    graph.add((node, ARGOS.verifiedBy, NORMS["CH-ret-001"]))
    graph.add((NORMS["CH-ret-001"], ARGOS.challengeId, Literal("ret-001")))
    return graph


@pytest.fixture
def world(migrated_db: str) -> tuple[str, str, OntologyStore, GraphStore]:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    graph_store = GraphStore(migrated_db)
    classify_new_columns(graph_store, probe_runner(migrated_db), system_id)
    store_version(migrated_db, "1.0.0", date(2026, 1, 1), _ontology(), HASH, {}, b"sig")
    return migrated_db, system_id, OntologyStore(migrated_db, "1.0.0"), graph_store


def test_a_run_is_persisted_journaled_and_announced(
    world: tuple[str, str, OntologyStore, GraphStore],
) -> None:
    dsn, system_id, ontology, graph_store = world
    bus = RecordingBus()
    run = resolve(
        dsn,
        ontology,
        StoreSelectorResolver(graph_store),
        {"system_ids": [system_id]},
        CAMPAIGN,
        bus,
        date(2026, 9, 16),
    )
    [row] = run.plan
    health = parse_selector(
        {
            "label": "Column",
            "category": "special_category.health",
            "min_confidence": 0.5,
            "missing": False,
        }
    )
    cypher, params = compile_selector(health, 500)
    expected = sorted(r["key"] for r in graph_store.query(cypher, params, NODE_COLUMNS))
    assert expected and row["node_keys"] == expected
    assert (run.ontology_version, run.pairs, run.nodes_total) == ("1.0.0", 1, len(expected))
    with psycopg.connect(dsn) as conn:
        stored = conn.execute(
            "SELECT campaign_id, ontology_version, resolved_for, scope, plan, pairs, nodes_total "
            "FROM argos.applicability_runs WHERE id = %s",
            (run.run_id,),
        ).fetchone()
        journal = conn.execute(
            "SELECT actor, payload FROM argos.audit_journal WHERE action = 'applicability.resolve'"
        ).fetchall()
    assert stored == (
        uuid.UUID(CAMPAIGN),
        "1.0.0",
        date(2026, 9, 16),
        {"system_ids": [system_id]},
        run.plan,
        1,
        len(expected),
    )
    assert journal == [
        (
            "system:resolver",
            {
                "run": run.run_id,
                "ontology": "1.0.0",
                "at": "2026-09-16",
                "pairs": 1,
                "nodes": len(expected),
            },
        )
    ]
    assert bus.published == [
        (
            EVENT_SUBJECT,
            EVENT_TYPE,
            {"run_id": run.run_id, "campaign_id": CAMPAIGN, "ontology": "1.0.0", "pairs": 1},
        )
    ]


def test_a_scope_outside_the_inventory_gives_an_empty_run(
    world: tuple[str, str, OntologyStore, GraphStore],
) -> None:
    dsn, _, ontology, graph_store = world
    run = resolve(dsn, ontology, StoreSelectorResolver(graph_store), {"system_ids": ["nowhere"]})
    assert (run.pairs, run.nodes_total, run.plan) == (0, 0, [])


def test_small_pages_resolve_the_same_nodes(
    world: tuple[str, str, OntologyStore, GraphStore],
) -> None:
    _, _, _, graph_store = world
    live_columns = parse_selector({"label": "Column", "missing": False})
    whole = StoreSelectorResolver(graph_store).resolve(live_columns)
    assert len(whole) > 5
    assert StoreSelectorResolver(graph_store, page_size=2).resolve(live_columns) == whole


def test_obligations_not_yet_in_force_are_left_out(
    world: tuple[str, str, OntologyStore, GraphStore],
) -> None:
    dsn, _, _, graph_store = world
    graph = _ontology()
    graph.add((NORMS["OBL-TEST-HEALTH-RETENTION"], ARGOS.inForceFrom, Literal(date(2029, 3, 26))))
    store_version(dsn, "1.1.0", date(2026, 2, 1), graph, "c" * 64, {}, b"sig")
    later = OntologyStore(dsn, "1.1.0")
    selectors = StoreSelectorResolver(graph_store)
    assert resolve(dsn, later, selectors, {}, at=date(2026, 9, 16)).pairs == 0
    assert resolve(dsn, later, selectors, {}, at=date(2029, 3, 26)).pairs == 1


def test_runs_are_immutable(world: tuple[str, str, OntologyStore, GraphStore]) -> None:
    dsn, _, ontology, graph_store = world
    run = resolve(dsn, ontology, StoreSelectorResolver(graph_store), {})
    with psycopg.connect(dsn) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE argos.applicability_runs SET pairs = 0 WHERE id = %s", (run.run_id,))
