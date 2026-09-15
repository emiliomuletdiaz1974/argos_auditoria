"""ARG-024 · deterministic classification of the simulated sources matches the ground truth."""

from collections.abc import Callable
from typing import Any

import pytest
from fixtures.ground_truth import load_ground_truth

from argos_connector.probes import ProbeResult, ProbeSpec
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore

from .inventory_helpers import probe_runner, scan_and_ingest

pytestmark = pytest.mark.integration

EDGES = (
    "MATCH (:System {id: $sid})-[:CONTAINS*2]->(t:Table)-[:CONTAINS]->(c:Column)"
    "-[r:CLASSIFIED_AS]->(k:Category) RETURN c.qualified_name, k.name, r.method, r.confidence"
)


def _edges(store: GraphStore, system_id: str) -> dict[str, tuple[str, str, float]]:
    rows = store.query(EDGES, {"sid": system_id}, ("column", "category", "method", "confidence"))
    return {r["column"]: (r["category"], r["method"], r["confidence"]) for r in rows}


@pytest.mark.parametrize("name", ["dev-source-postgres", "dev-source-mariadb"])
def test_classification_matches_the_ground_truth(migrated_db: str, name: str) -> None:
    system_id = scan_and_ingest(migrated_db, name)
    store = GraphStore(migrated_db)
    summary = classify_new_columns(store, probe_runner(migrated_db), system_id)
    assert summary.probe_failures == 0

    truth = load_ground_truth()
    expected = {c.column: (c.category, c.method) for c in truth.classifications if c.system == name}
    edges = _edges(store, system_id)
    found = {column: (category, method) for column, (category, method, _) in edges.items()}
    assert found == expected
    for column, (_, method, confidence) in edges.items():
        assert confidence == (1.0 if method.startswith("validator:") else 0.6), column
    for system, column in truth.unclassified:
        if system == name:
            assert column not in edges


def test_a_second_pass_leaves_classified_columns_alone(migrated_db: str) -> None:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    classify_new_columns(store, probe_runner(migrated_db), system_id)
    probes: list[ProbeSpec] = []
    real = probe_runner(migrated_db)

    def counting(sid: str, spec: ProbeSpec) -> ProbeResult:
        probes.append(spec)
        return real(sid, spec)

    again = classify_new_columns(store, counting, system_id)
    assert (again.dictionary, again.validated) == (0, 0)
    assert probes == []


def test_a_failing_validation_probe_keeps_the_dictionary_result(migrated_db: str) -> None:
    system_id = scan_and_ingest(migrated_db, "dev-source-mariadb")
    store = GraphStore(migrated_db)

    def failing(sid: str, spec: ProbeSpec) -> ProbeResult:
        return ProbeResult("p", "sample", False, {"error": "OperationalError"}, 1, 0, 1)

    summary = classify_new_columns(store, failing, system_id)
    assert summary.probe_failures == 1 and summary.validated == 0
    edges = _edges(store, system_id)
    assert edges["billing.patient_mirror.dni_number"][:2] == ("official_identifier", "dict")
    assert edges["billing.patient_mirror.iban"][:2] == ("financial_data", "dict")


def test_validation_uses_one_sample_probe_per_table(migrated_db: str) -> None:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    real: Callable[[str, ProbeSpec], ProbeResult] = probe_runner(migrated_db)
    probes: list[dict[str, Any]] = []

    def recording(sid: str, spec: ProbeSpec) -> ProbeResult:
        probes.append({"target": spec.target, **dict(spec.params)})
        return real(sid, spec)

    classify_new_columns(store, recording, system_id)
    assert probes == [
        {
            "target": "clinic.patient_documents",
            "columns": ["dni_number", "iban"],
            "k": 200,
            "validators": ["dni", "iban_es"],
        }
    ]
