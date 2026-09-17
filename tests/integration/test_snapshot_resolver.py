"""ARG-042 · the snapshot answers the same selectors as the live graph."""

import pytest
from fixtures.applicability_ground_truth import load_applicability_truth
from fixtures.demo_review import apply_demo_review

from argos_challenges.snapshot_resolver import SnapshotSelectorResolver
from argos_inventory.ai_discovery.detect import discover_ai
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore
from argos_inventory.versioning.snapshots import take_snapshot, verify_snapshot
from argos_ontology.applicability import asset_classes, compiled_selector, load_asset_classes
from argos_ontology.resolver import StoreSelectorResolver
from argos_ontology.vocabulary import NORMS

from .inventory_helpers import probe_runner, scan_and_ingest

pytestmark = pytest.mark.integration

TRUTH = load_applicability_truth()


@pytest.fixture
def snapshot(migrated_db: str) -> tuple[str, GraphStore, str]:
    store = GraphStore(migrated_db)
    system_ids = {}
    for name in TRUTH.systems:
        system_ids[name] = scan_and_ingest(migrated_db, name)
        classify_new_columns(store, probe_runner(migrated_db), system_ids[name])
    discover_ai(store)
    apply_demo_review(store, migrated_db, system_ids)
    reference = take_snapshot(store, migrated_db, "campaign-test")
    return reference.id, store, migrated_db


def test_every_asset_class_resolves_the_same_nodes_as_the_live_graph(
    snapshot: tuple[str, GraphStore, str],
) -> None:
    snapshot_id, store, dsn = snapshot
    over_snapshot = SnapshotSelectorResolver(dsn, snapshot_id)
    over_graph = StoreSelectorResolver(store)
    classes = asset_classes(load_asset_classes())
    checked = 0
    for asset_class in classes:
        if asset_class.selector is None:
            continue
        selector = compiled_selector(asset_class)
        name = str(asset_class.iri).removeprefix(str(NORMS))
        assert over_snapshot.resolve(selector) == over_graph.resolve(selector), name
        checked += 1
    assert checked >= 8


def test_the_snapshot_keeps_the_status_of_the_confirmed_ai_system(
    snapshot: tuple[str, GraphStore, str],
) -> None:
    snapshot_id, _, dsn = snapshot
    resolver = SnapshotSelectorResolver(dsn, snapshot_id)
    ai_nodes = [node for node in resolver.nodes if node["label"] == "AISystem"]
    assert ai_nodes and all(node["status"] == "confirmed" for node in ai_nodes)
    assert verify_snapshot(dsn, snapshot_id)


def test_the_snapshot_does_not_move_when_the_live_graph_does(
    snapshot: tuple[str, GraphStore, str],
) -> None:
    snapshot_id, store, dsn = snapshot
    selector = compiled_selector(
        next(
            asset_class
            for asset_class in asset_classes(load_asset_classes())
            if str(asset_class.iri).endswith("AC-stored-health-data")
        )
    )
    over_snapshot = SnapshotSelectorResolver(dsn, snapshot_id)
    before = over_snapshot.resolve(selector)
    assert before
    # A column disappears from the source: the live graph marks it, the snapshot does not move.
    store.execute("MATCH (c:Column {key: $key}) SET c.missing = true", {"key": before[0].key})
    after_live = StoreSelectorResolver(store).resolve(selector)
    assert before[0] not in after_live
    assert SnapshotSelectorResolver(dsn, snapshot_id).resolve(selector) == before
