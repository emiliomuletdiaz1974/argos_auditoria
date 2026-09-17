"""ARG-033 · the base asset classes resolve against a scanned and classified inventory graph."""

from typing import Any

import pytest
from fixtures.ground_truth import load_ground_truth

from argos_inventory.ai_discovery.detect import discover_ai
from argos_inventory.api.selector import NODE_COLUMNS, compile_selector
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore
from argos_ontology.applicability import asset_classes, compiled_selector, load_asset_classes
from argos_ontology.vocabulary import NORMS
from integration.inventory_helpers import probe_runner, scan_and_ingest

pytestmark = pytest.mark.integration

PAGE = 500


def _resolve(store: GraphStore, name: str) -> list[dict[str, Any]]:
    [asset_class] = [ac for ac in asset_classes(load_asset_classes()) if ac.iri == NORMS[name]]
    cypher, params = compile_selector(compiled_selector(asset_class), PAGE)
    return store.query(cypher, params, NODE_COLUMNS)


@pytest.fixture
def inventory(migrated_db: str) -> tuple[GraphStore, str]:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    classify_new_columns(store, probe_runner(migrated_db), system_id)
    discover_ai(store)
    return store, system_id


def test_every_resolvable_base_class_runs_on_the_real_graph(
    inventory: tuple[GraphStore, str],
) -> None:
    store, _ = inventory
    for asset_class in asset_classes(load_asset_classes()):
        if asset_class.selector is None:
            continue
        cypher, params = compile_selector(compiled_selector(asset_class), PAGE)
        store.query(cypher, params, NODE_COLUMNS)  # must not raise on AGE 1.5.0


def test_health_data_matches_the_ground_truth(inventory: tuple[GraphStore, str]) -> None:
    store, _ = inventory
    found = {row["qualified_name"] for row in _resolve(store, "AC-stored-health-data")}
    expected = {
        c.column
        for c in load_ground_truth().classifications
        if c.system == "dev-source-postgres" and c.category == "special_category.health"
    }
    assert expected and expected <= found


def test_unclassified_and_classified_columns_partition_the_live_columns(
    inventory: tuple[GraphStore, str],
) -> None:
    store, _ = inventory
    unclassified = {row["key"] for row in _resolve(store, "AC-unclassified-column")}
    classified = {
        row["key"]
        for row in store.query(
            "MATCH (c:Column)-[:CLASSIFIED_AS]->(:Category) RETURN DISTINCT c.key",
            columns=("key",),
        )
    }
    live = {
        row["key"]
        for row in store.query(
            "MATCH (c:Column) WHERE coalesce(c.missing, false) = false RETURN c.key",
            columns=("key",),
        )
    }
    assert unclassified and classified
    assert unclassified.isdisjoint(classified)
    assert unclassified | classified == live


def test_pending_ai_systems_are_found(inventory: tuple[GraphStore, str]) -> None:
    store, _ = inventory
    names = {row["name"] for row in _resolve(store, "AC-pending-ai-system")}
    assert "table:readmission_risk" in names
