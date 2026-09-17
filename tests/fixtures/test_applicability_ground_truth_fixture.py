"""The applicability ground truth agrees with the inventory ground truth and library (F04-18)."""

from datetime import date

import pytest
from rdflib import Literal, URIRef

from argos_ontology.traceability import library_graph
from argos_ontology.vocabulary import ARGOS, NORMS
from fixtures.applicability_ground_truth import load_applicability_truth
from fixtures.demo_review import load_demo_review
from fixtures.ground_truth import load_ground_truth

TRUTH = load_applicability_truth()
INVENTORY = load_ground_truth()
REVIEW = load_demo_review()
LIBRARY = library_graph()
# Asset class -> category prefix of its selector (library/ontology/asset-classes/base.ttl).
CATEGORY_OF_CLASS = {
    "AC-stored-personal-data": "personal_data",
    "AC-stored-identifier-data": "official_identifier",
    "AC-stored-contact-data": "contact_data",
    "AC-stored-financial-data": "financial_data",
    "AC-stored-health-data": "special_category.health",
    "AC-stored-special-category-data": "special_category",
}


def _node(system: str, column: str) -> str:
    return f"{system} {column}"


def _snapshot_columns() -> set[str]:
    return {
        _node(system, f"{table}.{column}")
        for system in TRUTH.systems
        for table, columns in INVENTORY.tables(system).items()
        for column in columns
    }


def test_the_snapshot_systems_are_relational_systems_of_the_inventory_ground_truth() -> None:
    for system in TRUTH.systems:
        assert INVENTORY.systems[system]["kind"] == "rdbms"


@pytest.mark.parametrize("asset_class", sorted(CATEGORY_OF_CLASS))
def test_classified_classes_follow_the_inventory_classifications(asset_class: str) -> None:
    prefix = CATEGORY_OF_CLASS[asset_class]
    expected = {
        _node(c.system, c.column)
        for c in INVENTORY.classifications
        if c.system in TRUTH.systems and c.category.startswith(prefix)
    }
    assert TRUTH.asset_classes[asset_class] == expected


def test_unclassified_columns_are_every_other_column_of_the_snapshot() -> None:
    classified = {_node(c.system, c.column) for c in INVENTORY.classifications}
    reviewed = {
        _node(system, column)
        for system, columns in REVIEW.no_personal_data.items()
        for column in columns
    }
    unclassified = TRUTH.asset_classes["AC-unclassified-column"]
    assert unclassified == _snapshot_columns() - classified - reviewed
    assert {_node(s, c) for s, c in INVENTORY.unclassified if s in TRUTH.systems} - reviewed <= (
        unclassified
    )


def test_ai_systems_are_the_score_column_candidates_split_by_the_dpo_confirmation() -> None:
    candidates = {
        _node(a.system, f"table:{a.detail_contains}")
        for a in INVENTORY.ai_candidates
        if a.system in TRUTH.systems and a.signal_kind == "score_column"
    }
    confirmed = {_node(ai.system, ai.name) for ai in REVIEW.ai_systems}
    assert TRUTH.asset_classes["AC-confirmed-ai-system"] == candidates & confirmed
    assert TRUTH.asset_classes["AC-pending-ai-system"] == candidates - confirmed


def _library_obligations(at: date) -> dict[str, tuple[set[str], set[str]]]:
    found: dict[str, tuple[set[str], set[str]]] = {}
    for obligation in LIBRARY.subjects(ARGOS.severity, None):
        assert isinstance(obligation, URIRef)
        since = LIBRARY.value(obligation, ARGOS.inForceFrom)
        if isinstance(since, Literal) and since.toPython() > at:
            continue
        challenges = {
            str(LIBRARY.value(ch, ARGOS.challengeId))
            for ch in LIBRARY.objects(obligation, ARGOS.verifiedBy)
        }
        if not challenges:
            continue
        classes = {
            str(ac).removeprefix(str(NORMS)) for ac in LIBRARY.objects(obligation, ARGOS.appliesTo)
        }
        found[str(obligation).removeprefix(str(NORMS))] = (classes, challenges)
    return found


@pytest.mark.parametrize("at", sorted(TRUTH.dates))
def test_each_date_lists_exactly_the_library_obligations_in_force_with_challenges(at: date) -> None:
    expected = {
        obligation: (set(spec.classes), set(spec.challenges))
        for obligation, spec in TRUTH.dates[at].items()
    }
    assert expected == _library_obligations(at)
