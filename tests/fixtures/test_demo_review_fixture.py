"""F04-23 · the synthetic DPO decisions only touch what the deterministic snapshot leaves open."""

from pathlib import Path

import pytest

from fixtures.applicability_ground_truth import load_applicability_truth
from fixtures.demo_review import DEMO_REVIEW_FILE, load_demo_review
from fixtures.ground_truth import load_ground_truth


def test_every_reviewed_column_exists_and_is_left_unclassified_by_the_classifier() -> None:
    review = load_demo_review()
    truth = load_ground_truth()
    classified = {(c.system, c.column) for c in truth.classifications}
    for system, columns in review.no_personal_data.items():
        tables = truth.tables(system)
        for column in columns:
            table, _, name = column.rpartition(".")
            assert name in tables[table], column
            assert (system, column) not in classified, column


def test_reviewed_columns_leave_the_unclassified_class_of_the_applicability_truth() -> None:
    review = load_demo_review()
    unclassified = load_applicability_truth().asset_classes["AC-unclassified-column"]
    for system, columns in review.no_personal_data.items():
        assert not {f"{system} {column}" for column in columns} & unclassified


def test_confirmed_ai_systems_are_discovered_candidates_with_a_valid_risk_class() -> None:
    review = load_demo_review()
    truth = load_ground_truth()
    confirmed = load_applicability_truth().asset_classes["AC-confirmed-ai-system"]
    assert review.reviewer.startswith("user:")
    for ai in review.ai_systems:
        assert ai.risk_class in {"prohibited", "high", "limited", "minimal"}
        assert any(
            c.system == ai.system and c.detail_contains in ai.name for c in truth.ai_candidates
        )
        assert f"{ai.system} {ai.name}" in confirmed


def test_a_reviewer_that_is_not_a_person_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    text = DEMO_REVIEW_FILE.read_text(encoding="utf-8")
    bad.write_text(text.replace("user:demo-dpo", "system:demo"), encoding="utf-8")
    with pytest.raises(ValueError, match="person"):
        load_demo_review(bad)
