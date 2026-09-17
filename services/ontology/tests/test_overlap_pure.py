"""ARG-038 · the overlap matrix shows where one control serves obligations of several norms."""

import csv
import io
import json

from rdflib import RDF, Graph, Literal

from argos_ontology.overlap import (
    OverlapRow,
    build_overlap,
    overlap_csv,
    overlap_json,
)
from argos_ontology.traceability import library_graph
from argos_ontology.vocabulary import ARGOS, NORMS, bind_prefixes


def _obligation(graph: Graph, obligation: str, norm: str, classes: list[str]) -> None:
    node = NORMS[obligation]
    article = NORMS[f"{norm}-1"]
    graph.add((NORMS[norm], RDF.type, ARGOS.Norm))
    graph.add((article, ARGOS.partOf, NORMS[norm]))
    graph.add((node, RDF.type, ARGOS.Obligation))
    graph.add((node, ARGOS.derivesFrom, article))
    for asset_class in classes:
        graph.add((node, ARGOS.appliesTo, NORMS[asset_class]))


def _graph() -> Graph:
    graph = bind_prefixes(Graph())
    _obligation(graph, "OBL-A-1", "A", ["AC-health", "AC-personal"])
    _obligation(graph, "OBL-B-1", "B", ["AC-health"])
    _obligation(graph, "OBL-B-2", "B", ["AC-personal"])
    _obligation(graph, "OBL-B-3", "B", ["AC-only-b"])
    graph.add((NORMS["OBL-A-1"], ARGOS.equivalentTo, NORMS["ENS-mp-info-3"]))
    return graph


def test_only_asset_classes_reached_by_several_norms_are_overlaps() -> None:
    assert build_overlap(_graph()) == [
        OverlapRow(
            asset_class="AC-health",
            norms=("A", "B"),
            obligations=("OBL-A-1", "OBL-B-1"),
            equivalences=("OBL-A-1=ENS-mp-info-3",),
        ),
        OverlapRow(
            asset_class="AC-personal",
            norms=("A", "B"),
            obligations=("OBL-A-1", "OBL-B-2"),
            equivalences=("OBL-A-1=ENS-mp-info-3",),
        ),
    ]


def test_an_obligation_without_a_declared_norm_does_not_create_overlaps() -> None:
    graph = _graph()
    graph.add((NORMS["OBL-X-1"], RDF.type, ARGOS.Obligation))
    graph.add((NORMS["OBL-X-1"], ARGOS.appliesTo, NORMS["AC-only-b"]))
    assert [row.asset_class for row in build_overlap(graph)] == ["AC-health", "AC-personal"]


def test_outputs_are_deterministic_json_and_semicolon_csv() -> None:
    rows = build_overlap(_graph())
    assert overlap_json(rows) == overlap_json(build_overlap(_graph()))
    assert json.loads(overlap_json(rows))[0]["norms"] == ["A", "B"]
    table = list(csv.reader(io.StringIO(overlap_csv(rows)), delimiter=";"))
    assert table[0] == ["asset_class", "norms", "obligations", "equivalences"]
    assert table[1] == ["AC-health", "A,B", "OBL-A-1,OBL-B-1", "OBL-A-1=ENS-mp-info-3"]


def test_the_shipped_library_overlaps_gdpr_and_ehds_on_health_data() -> None:
    by_class = {row.asset_class: row for row in build_overlap(library_graph())}
    health = by_class["AC-stored-health-data"]
    assert health.norms == ("EHDS", "RGPD")
    assert "OBL-RGPD-32-1" in health.obligations and "OBL-EHDS-9-1" in health.obligations


def test_a_norm_label_literal_is_not_mistaken_for_a_norm() -> None:
    graph = _graph()
    graph.add((NORMS["A"], ARGOS.eli, Literal("http://example.org/eli")))
    assert len(build_overlap(graph)) == 2
