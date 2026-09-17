"""ARG-033 · base asset classes carry selectors the inventory API accepts."""

import json

from rdflib import RDF, Graph, Literal

from argos_ontology.applicability import (
    asset_class_errors,
    asset_classes,
    compiled_selector,
    load_asset_classes,
)
from argos_ontology.vocabulary import ARGOS, NORMS, load_core

BASE = load_asset_classes()
EXPECTED = {
    "AC-stored-personal-data",
    "AC-stored-identifier-data",
    "AC-stored-contact-data",
    "AC-stored-financial-data",
    "AC-stored-health-data",
    "AC-stored-special-category-data",
    "AC-unclassified-column",
    "AC-pending-ai-system",
    "AC-confirmed-ai-system",
    "AC-missing-table",
    "AC-cross-border-flow",
}


def _names(graph: Graph) -> set[str]:
    return {str(ac.iri).removeprefix(str(NORMS)) for ac in asset_classes(graph)}


def test_the_base_classes_are_the_documented_ones() -> None:
    assert _names(BASE) == EXPECTED


def test_every_base_class_is_sound() -> None:
    assert asset_class_errors(BASE) == []


def test_selectors_compile_with_the_inventory_rules() -> None:
    by_name = {str(ac.iri).removeprefix(str(NORMS)): ac for ac in asset_classes(BASE)}
    health = compiled_selector(by_name["AC-stored-health-data"])
    assert (health.label, health.category, health.missing) == (
        "Column",
        "special_category.health",
        False,
    )
    assert compiled_selector(by_name["AC-unclassified-column"]).unclassified is True
    assert compiled_selector(by_name["AC-pending-ai-system"]).status == "pending"


def test_the_cross_border_flow_is_declared_pending_not_resolvable() -> None:
    [flow] = [ac for ac in asset_classes(BASE) if ac.iri == NORMS["AC-cross-border-flow"]]
    assert flow.selector is None
    assert flow.verification_pending is not None


def test_categories_are_the_graph_ones_never_spanish() -> None:
    for ac in asset_classes(BASE):
        if ac.selector and "category" in ac.selector:
            assert ac.selector["category"].split(".")[0] in {
                "personal_data",
                "official_identifier",
                "contact_data",
                "financial_data",
                "special_category",
            }


def test_the_core_and_the_base_classes_parse_together() -> None:
    merged = load_core() + BASE
    assert (NORMS["AC-stored-health-data"], ARGOS.graphLabel, Literal("Column")) in merged


def _with(selector_json: str | None, pending: str | None = None) -> Graph:
    graph = Graph()
    node = NORMS["AC-test"]
    graph.add((node, RDF.type, ARGOS.AssetClass))
    graph.add((node, ARGOS.graphLabel, Literal("Column")))
    if selector_json is not None:
        graph.add((node, ARGOS.selectorJson, Literal(selector_json)))
    if pending is not None:
        graph.add((node, ARGOS.verificationPending, Literal(pending)))
    return graph


def test_broken_asset_classes_are_reported() -> None:
    cases = {
        "invalid selector": _with(json.dumps({"label": "Column", "category": None})),
        "not a JSON object": _with("[1, 2]"),
        "differs from selector label": _with(json.dumps({"label": "Table"})),
        "no selector and no verificationPending": _with(None),
        "selector fields not allowed": _with(json.dumps({"label": "Column", "system_ids": ["a"]})),
    }
    for message, graph in cases.items():
        [error] = asset_class_errors(graph)
        assert message in error, (message, error)
    assert asset_class_errors(_with(None, pending="no country yet")) == []
