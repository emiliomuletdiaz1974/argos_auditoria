"""F04-18 · the resolver on the demo snapshot gives exactly the applicability ground truth."""

from datetime import date

import pytest
from fixtures.applicability_ground_truth import ExpectedRequirement, load_applicability_truth
from fixtures.demo_review import apply_demo_review

from argos_inventory.ai_discovery.detect import discover_ai
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore
from argos_ontology.resolver import StoreSelectorResolver, resolve
from argos_ontology.store import OntologyStore, store_version
from argos_ontology.traceability import library_graph
from argos_ontology.vocabulary import NORMS
from integration.inventory_helpers import probe_runner, scan_and_ingest

pytestmark = pytest.mark.integration

TRUTH = load_applicability_truth()
NODE_NAMES = (
    "MATCH (s:System) WITH s MATCH (n) WHERE coalesce(n.system_id, n.id) = s.id "
    "RETURN n.key, s.name, coalesce(n.qualified_name, n.name)"
)


def test_the_plan_matches_the_ground_truth_on_every_date(migrated_db: str) -> None:
    store = GraphStore(migrated_db)
    system_ids = {}
    for name in TRUTH.systems:
        system_ids[name] = scan_and_ingest(migrated_db, name)
        classify_new_columns(store, probe_runner(migrated_db), system_ids[name])
    discover_ai(store)
    apply_demo_review(store, migrated_db, system_ids)
    names = {
        str(row["key"]): f"{row['system']} {row['name']}"
        for row in store.query(NODE_NAMES, columns=("key", "system", "name"))
    }
    store_version(migrated_db, "1.0.0", date(2024, 8, 1), library_graph(), "e" * 64, {}, b"demo")
    ontology = OntologyStore(migrated_db, "1.0.0")
    for at in sorted(TRUTH.dates):
        run = resolve(migrated_db, ontology, StoreSelectorResolver(store), {}, at=at)
        assert run.skipped == [], at
        found = {
            ExpectedRequirement(
                row["obligation"].removeprefix(str(NORMS)),
                row["asset_class"].removeprefix(str(NORMS)),
                row["challenge_id"],
                frozenset(names[key] for key in row["node_keys"]),
            )
            for row in run.plan
        }
        expected = TRUTH.expected_plan(at)
        assert (at, sorted(found - expected)) == (at, [])
        assert (at, sorted(expected - found)) == (at, [])
