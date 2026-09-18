"""F06-02 · the golden sets are honest before anything is measured against them.

Written before the services they will measure, like the campaign ground truth of F05-01. What this
test defends is that a golden set cannot quietly become easier: every expected citation has to
exist in the corpus, every labelled column has to exist in the inventory, every trap has to be a
trap, and every threshold has to say why it is that number.
"""

from collections import Counter

import pytest

from argos_ontology.traceability import load_challenge_catalog
from fixtures.goldens import (
    CATEGORIES,
    SUITES,
    Case,
    corpus_references,
    inventory_columns,
    load_goldens,
    load_thresholds,
)

MINIMUM_QUESTIONS = 20
MINIMUM_TRAPS = 4


@pytest.mark.parametrize("suite", sorted(SUITES))
def test_every_suite_loads_and_its_cases_are_unique(suite: str) -> None:
    cases = load_goldens(suite)
    assert cases, f"the suite {suite} is empty"
    repeated = [name for name, count in Counter(c.id for c in cases).items() if count > 1]
    assert repeated == []


@pytest.mark.parametrize("suite", sorted(SUITES))
def test_every_case_says_why_it_is_there(suite: str) -> None:
    assert [c.id for c in load_goldens(suite) if not c.why.strip()] == []


def test_the_dpo_script_has_twenty_questions_and_its_traps() -> None:
    cases = load_goldens("rag")
    assert len(cases) >= MINIMUM_QUESTIONS
    assert sum(1 for c in cases if c.kind == "trap") >= MINIMUM_TRAPS


def test_every_expected_citation_exists_in_the_corpus() -> None:
    """A question whose answer is not in the corpus measures nothing."""
    references = corpus_references()
    unknown = [
        (c.id, citation)
        for c in load_goldens("rag")
        for citation in c.expected.get("citations", [])
        if citation not in references
    ]
    assert unknown == []


def test_a_trap_question_expects_a_refusal_and_cites_nothing() -> None:
    for case in load_goldens("rag"):
        if case.kind != "trap":
            continue
        assert case.expected.get("sufficient") is False, case.id
        assert case.expected.get("citations", []) == [], case.id


def test_a_plain_question_expects_an_answer_with_at_least_one_citation() -> None:
    for case in load_goldens("rag"):
        if case.kind != "plain":
            continue
        assert case.expected.get("sufficient") is True, case.id
        assert case.expected.get("citations"), case.id


def test_every_labelled_column_exists_in_the_inventory() -> None:
    columns = inventory_columns()
    unknown = [
        (case.id, key)
        for case in load_goldens("classify")
        for key in [(case.input["system"], case.input["column"])]
        if key not in columns
    ]
    assert unknown == []


def test_every_expected_category_is_one_of_the_closed_vocabulary() -> None:
    for case in load_goldens("classify"):
        category = case.expected.get("category")
        assert category is None or category in CATEGORIES, case.id


def test_the_classify_traps_are_the_doubtful_columns() -> None:
    """A doubtful column is one the classifier must leave alone, not one it must guess."""
    traps = [c for c in load_goldens("classify") if c.kind == "trap"]
    assert traps
    assert all(c.expected.get("category") is None for c in traps)


def test_every_challenge_to_generate_is_in_the_catalog() -> None:
    catalog = load_challenge_catalog()
    unknown = [
        (c.id, c.expected["challenge_id"])
        for c in load_goldens("generate")
        if c.expected["challenge_id"] not in catalog
    ]
    assert unknown == []


def test_every_obligation_to_generate_from_exists() -> None:
    references = corpus_references()
    obligations = {reference.obligation for found in references.values() for reference in found}
    unknown = [
        (c.id, c.input["obligation"])
        for c in load_goldens("generate")
        if c.input["obligation"] not in obligations
    ]
    assert unknown == []


def test_a_report_trap_offers_a_figure_that_is_not_in_its_data() -> None:
    """If the offending figure were in the data, the case would not be a trap."""
    for case in load_goldens("reports"):
        if case.kind != "trap":
            continue
        offending = str(case.expected["offending"])
        assert case.expected["accepted"] is False, case.id
        assert offending not in _figures(case), case.id


def test_a_plain_report_case_only_uses_figures_of_its_data() -> None:
    for case in load_goldens("reports"):
        if case.kind != "plain":
            continue
        assert case.expected["accepted"] is True, case.id
        assert all(figure in _figures(case) for figure in case.expected["figures"]), case.id


def _figures(case: Case) -> set[str]:
    return {str(value) for value in case.input["figures"].values()}


@pytest.mark.parametrize("suite", sorted(SUITES))
def test_every_suite_has_a_threshold_with_its_reason(suite: str) -> None:
    thresholds = load_thresholds()
    assert suite in thresholds, f"the suite {suite} has no threshold"
    entry = thresholds[suite]
    assert 0 < float(entry["minimum"]) <= 1
    assert entry["why"].strip()


def test_a_threshold_without_its_suite_is_an_error() -> None:
    """The harness must not give as good what it did not measure."""
    assert set(load_thresholds()) <= set(SUITES)
