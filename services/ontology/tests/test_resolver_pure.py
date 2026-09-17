"""ARG-039 · the applicability plan crosses obligations, asset classes and inventory nodes."""

from collections.abc import Sequence
from datetime import date

import pytest
from rdflib import RDF, RDFS, XSD, Graph, Literal

from argos_inventory.api.selector import Selector
from argos_ontology.resolver import (
    Requirement,
    ResolvedNode,
    build_plan,
    check_scope,
    in_force,
    requirements,
)
from argos_ontology.vocabulary import ARGOS, NORMS, bind_prefixes

HEALTH = '{"label": "Column", "category": "special_category.health", "missing": false}'


def _ontology() -> Graph:
    graph = bind_prefixes(Graph())
    for name, selector in (("AC-health", HEALTH), ("AC-health-copy", HEALTH)):
        graph.add((NORMS[name], RDF.type, ARGOS.AssetClass))
        graph.add((NORMS[name], ARGOS.selectorJson, Literal(selector)))
    graph.add((NORMS["AC-pending"], RDF.type, ARGOS.AssetClass))
    graph.add((NORMS["AC-pending"], ARGOS.verificationPending, Literal("no selector yet")))
    obligations: tuple[tuple[str, list[str], list[str]], ...] = (
        ("OBL-B", ["AC-health", "AC-health-copy"], ["ret-001", "ret-002"]),
        ("OBL-A", ["AC-pending"], ["acc-001"]),
        ("OBL-C", ["AC-health"], []),
    )
    for obligation, classes, challenges in obligations:
        node = NORMS[obligation]
        graph.add((node, RDF.type, ARGOS.Obligation))
        graph.add((node, RDFS.label, Literal(f"Label {obligation}", lang="es")))
        graph.add((node, ARGOS.severity, Literal("high")))
        for asset_class in classes:
            graph.add((node, ARGOS.appliesTo, NORMS[asset_class]))
        for challenge in challenges:
            graph.add((node, ARGOS.verifiedBy, NORMS[f"CH-{challenge}"]))
            graph.add((NORMS[f"CH-{challenge}"], ARGOS.challengeId, Literal(challenge)))
    return graph


class FakeSelectors:
    def __init__(self, nodes: Sequence[ResolvedNode]) -> None:
        self.nodes = list(nodes)
        self.calls: list[Selector] = []

    def resolve(self, selector: Selector) -> list[ResolvedNode]:
        self.calls.append(selector)
        return list(self.nodes)


NODES = [
    ResolvedNode("col-2", "sys-b"),
    ResolvedNode("col-1", "sys-a"),
]


def test_requirements_are_the_obligation_class_challenge_triples_in_a_stable_order() -> None:
    found = requirements(_ontology())
    assert [(r.obligation, r.asset_class, r.challenge_id) for r in found] == [
        (str(NORMS["OBL-A"]), str(NORMS["AC-pending"]), "acc-001"),
        (str(NORMS["OBL-B"]), str(NORMS["AC-health"]), "ret-001"),
        (str(NORMS["OBL-B"]), str(NORMS["AC-health"]), "ret-002"),
        (str(NORMS["OBL-B"]), str(NORMS["AC-health-copy"]), "ret-001"),
        (str(NORMS["OBL-B"]), str(NORMS["AC-health-copy"]), "ret-002"),
    ]
    assert found[0].selector is None
    assert found[1].selector == {
        "label": "Column",
        "category": "special_category.health",
        "missing": False,
    }
    assert found[1].label == "Label OBL-B"
    assert found[1].severity == "high"


def test_the_plan_has_one_row_per_requirement_with_its_sorted_nodes_and_its_why() -> None:
    selectors = FakeSelectors(NODES)
    plan, skipped = build_plan(requirements(_ontology()), selectors, {})
    assert len(plan) == 4
    assert plan[0] == {
        "obligation": str(NORMS["OBL-B"]),
        "label": "Label OBL-B",
        "severity": "high",
        "asset_class": str(NORMS["AC-health"]),
        "selector": {"label": "Column", "category": "special_category.health", "missing": False},
        "challenge_id": "ret-001",
        "node_keys": ["col-1", "col-2"],
    }
    assert skipped == [
        {
            "obligation": str(NORMS["OBL-A"]),
            "asset_class": str(NORMS["AC-pending"]),
            "challenge_id": "acc-001",
            "reason": "asset class without selector: no selector yet",
        }
    ]


def test_each_distinct_selector_is_resolved_once_per_run() -> None:
    selectors = FakeSelectors(NODES)
    build_plan(requirements(_ontology()), selectors, {})
    assert len(selectors.calls) == 1


def test_the_scope_keeps_only_nodes_of_its_systems_and_drops_empty_rows() -> None:
    plan, _ = build_plan(requirements(_ontology()), FakeSelectors(NODES), {"system_ids": ["sys-b"]})
    assert {tuple(row["node_keys"]) for row in plan} == {("col-2",)}
    empty, _ = build_plan(requirements(_ontology()), FakeSelectors(NODES), {"system_ids": ["zz"]})
    assert empty == []


def test_an_invalid_selector_is_skipped_with_its_reason() -> None:
    requirement = Requirement("urn:o", "o", "low", "urn:ac", {"label": "Nope"}, None, "chk-001")
    plan, skipped = build_plan([requirement], FakeSelectors(NODES), {})
    assert plan == []
    assert skipped[0]["reason"].startswith("invalid selector: unknown node label")


@pytest.mark.parametrize(
    "scope",
    [
        {"system_ids": "sys-a"},
        {"system_ids": [1]},
        {"system_ids": []},
        {"systems": ["sys-a"]},
    ],
)
def test_scopes_are_checked(scope: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="scope"):
        check_scope(scope)


def test_a_valid_scope_is_normalised() -> None:
    assert check_scope({}) == {}
    assert check_scope({"system_ids": ["b", "a", "b"]}) == {"system_ids": ["a", "b"]}


def test_only_obligations_in_force_on_the_date_are_required() -> None:
    graph = _ontology()
    later = NORMS["OBL-B"]
    graph.add((later, ARGOS.inForceFrom, Literal(date(2029, 3, 26), datatype=XSD.date)))
    ended = NORMS["OBL-A"]
    graph.add((ended, ARGOS.inForceUntil, Literal(date(2026, 1, 1), datatype=XSD.date)))
    assert requirements(graph, date(2026, 9, 16)) == []
    assert {r.obligation for r in requirements(graph, date(2029, 3, 26))} == {str(later)}
    assert {r.obligation for r in requirements(graph)} == {str(later), str(ended)}


def test_in_force_bounds_are_inclusive_from_and_exclusive_until() -> None:
    start, end = date(2027, 1, 1), date(2028, 1, 1)
    assert not in_force(date(2026, 12, 31), start, end)
    assert in_force(start, start, end)
    assert not in_force(end, start, end)
    assert in_force(None, start, end)
