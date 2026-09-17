"""ARG-034 · coherence findings on a scanned, classified inventory with its treatments."""

import pytest

from argos_inventory.catalog.treatments import import_treatments
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.model import system_key, treatment_key
from argos_inventory.graph.store import GraphStore
from argos_ontology.shacl import run_shapes
from integration.inventory_helpers import probe_runner, scan_and_ingest

pytestmark = pytest.mark.integration

DPO = "user:0192b000-0000-7000-8000-00000000d0c0"
HEADER = b"id;name;legal_basis;retention;systems\n"


@pytest.fixture
def inventory(migrated_db: str) -> tuple[GraphStore, str, str]:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    classify_new_columns(store, probe_runner(migrated_db), system_id)
    return store, migrated_db, system_id


def _findings(store: GraphStore) -> set[tuple[str, str, str]]:
    return {(f.node, f.shape, f.severity) for f in run_shapes(store)}


def test_gaps_in_the_record_of_processing_activities_are_found(
    inventory: tuple[GraphStore, str, str],
) -> None:
    store, dsn, system_id = inventory
    import_treatments(store, dsn, HEADER + b"T-001;Historia clinica;;;\n", DPO)
    assert _findings(store) == {
        (system_key(system_id), "HealthDataSystemShape", "violation"),
        (treatment_key("T-001"), "TreatmentShape", "violation"),
        (treatment_key("T-001"), "TreatmentShape", "warning"),
    }


def test_a_complete_declaration_leaves_no_findings(inventory: tuple[GraphStore, str, str]) -> None:
    store, dsn, _ = inventory
    record = HEADER + b"T-001;Historia clinica;GDPR 9.2.h;15 years;dev-source-postgres\n"
    import_treatments(store, dsn, record, DPO)
    assert _findings(store) == set()


def test_a_confirmed_ai_system_without_risk_class_is_found(
    inventory: tuple[GraphStore, str, str],
) -> None:
    store, dsn, _ = inventory
    record = HEADER + b"T-001;Historia clinica;GDPR 9.2.h;15 years;dev-source-postgres\n"
    import_treatments(store, dsn, record, DPO)
    store.execute("CREATE (:AISystem {key: 'ai-planted', status: 'confirmed'})")
    assert _findings(store) == {("ai-planted", "ConfirmedAISystemShape", "violation")}
