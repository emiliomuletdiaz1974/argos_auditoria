"""ARG-027 · flows between the simulated sources: engine catalog and structural matching."""

from typing import Any

import pytest
from fixtures.ground_truth import load_ground_truth

from argos_connector.probes import ProbeResult, ProbeSpec
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.flows.detect import detect_engine_links, detect_structural
from argos_inventory.graph.store import GraphStore

from .inventory_helpers import probe_runner, scan_and_ingest

pytestmark = pytest.mark.integration

FLOWS = (
    "MATCH (a:System)-[f:FLOWS_TO]->(b:System) "
    "RETURN a.id, b.id, b.name, b.external, f.method, f.confidence, f.confirmed"
)
FLOW_COLUMNS = ("source", "target", "name", "external", "method", "confidence", "confirmed")


def _flows(store: GraphStore) -> list[dict[str, Any]]:
    return store.query(FLOWS, columns=FLOW_COLUMNS)


def _prepared(dsn: str) -> tuple[str, str, GraphStore]:
    postgres = scan_and_ingest(dsn, "dev-source-postgres")
    mariadb = scan_and_ingest(dsn, "dev-source-mariadb")
    store = GraphStore(dsn)
    runner = probe_runner(dsn)
    classify_new_columns(store, runner, postgres)
    classify_new_columns(store, runner, mariadb)
    return postgres, mariadb, store


def test_flows_match_the_ground_truth(migrated_db: str) -> None:
    postgres, mariadb, store = _prepared(migrated_db)
    ids = {"dev-source-postgres": postgres, "dev-source-mariadb": mariadb}
    engine = detect_engine_links(store, migrated_db, probe_runner(migrated_db), postgres)
    assert (engine.engine_links, engine.probe_failures) == (1, 0)
    assert detect_structural(store) == 1

    found = _flows(store)
    for expected in load_ground_truth().flows:
        source, target = ids[expected.source], ids[expected.target]
        matches = [
            f
            for f in found
            if f["method"] == expected.method
            and (
                {f["source"], f["target"]} == {source, target}
                if expected.undirected
                else (f["source"], f["target"]) == (source, target)
            )
        ]
        assert len(matches) == 1, expected
        assert expected.min_confidence <= matches[0]["confidence"] <= expected.max_confidence
        assert matches[0]["confirmed"] is False
    assert len(found) == len(load_ground_truth().flows)


def test_detection_is_idempotent_and_keeps_confirmations(migrated_db: str) -> None:
    postgres, _, store = _prepared(migrated_db)
    detect_engine_links(store, migrated_db, probe_runner(migrated_db), postgres)
    store.execute("MATCH ()-[f:FLOWS_TO {method: 'engine_catalog'}]->() SET f.confirmed = true")
    detect_engine_links(store, migrated_db, probe_runner(migrated_db), postgres)
    detect_structural(store)
    detect_structural(store)
    flows = _flows(store)
    assert len(flows) == 2
    assert {f["method"]: f["confirmed"] for f in flows} == {
        "engine_catalog": True,
        "structural": False,
    }


def test_an_unregistered_link_target_becomes_an_external_system(migrated_db: str) -> None:
    postgres = scan_and_ingest(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)

    def fake(sid: str, spec: ProbeSpec) -> ProbeResult:
        assert spec.kind == "check_config" and spec.statement is not None
        rows = [{"name": "erp_link", "options": "['host=erp.example.invalid', 'port=5432']"}]
        return ProbeResult("p", "check_config", True, {"rows": rows}, 1, 1, 1)

    summary = detect_engine_links(store, migrated_db, fake, postgres)
    assert summary.engine_links == 1
    [flow] = _flows(store)
    assert (flow["source"], flow["external"], flow["name"], flow["method"]) == (
        postgres,
        True,
        "erp.example.invalid",
        "engine_catalog",
    )
    assert flow["target"] is None


def test_systems_without_an_engine_catalog_are_skipped(migrated_db: str) -> None:
    files = scan_and_ingest(migrated_db, "dev-files-local")
    calls: list[ProbeSpec] = []

    def never(sid: str, spec: ProbeSpec) -> ProbeResult:
        calls.append(spec)
        raise AssertionError("no probe expected")

    summary = detect_engine_links(GraphStore(migrated_db), migrated_db, never, files)
    assert (summary.engine_links, summary.probe_failures, calls) == (0, 0, [])
