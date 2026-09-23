"""ARG-025 · triage of model proposals, prompt hash and the null model (pure)."""

import re

import pytest

from argos_inventory.classify.assisted import (
    ACCEPT,
    REVIEW,
    SYSTEM_PROMPT,
    ColumnContext,
    NullModel,
    Proposal,
    decide_review,
    prompt_hash,
    triage,
)
from argos_inventory.graph.model import CATEGORIES
from argos_inventory.graph.store import GraphStore

KEYS = frozenset({"a", "b", "c", "d"})
UNUSED_DSN = "postgresql://unused@127.0.0.1:1/unused"


def test_triage_applies_the_thresholds_and_discards_invalid_proposals() -> None:
    proposals = [
        Proposal("a", "personal_data", 0.90),
        Proposal("b", "special_category.health", 0.70),
        Proposal("c", "no_personal_data", 0.20),
        Proposal("d", "dato_personal", 0.99),  # category not in the closed list
        Proposal("zz", "personal_data", 0.99),  # key not in the batch
        Proposal("a", "contact_data", 0.95),  # second proposal for the same key
        Proposal("d", "personal_data", 1.5),  # confidence out of range
    ]
    result = triage(proposals, KEYS)
    assert [p.key for p in result.accepted] == ["a"]
    assert [p.key for p in result.review] == ["b"]
    assert [p.key for p in result.ignored] == ["c"]
    assert len(result.invalid) == 4
    assert (ACCEPT, REVIEW) == (0.85, 0.50)


@pytest.mark.parametrize(
    ("confidence", "bucket"),
    [(0.85, "accepted"), (0.8499, "review"), (0.5, "review"), (0.4999, "ignored")],
)
def test_threshold_edges(confidence: float, bucket: str) -> None:
    result = triage([Proposal("a", "personal_data", confidence)], KEYS)
    assert [p.key for p in getattr(result, bucket)] == ["a"]


@pytest.mark.parametrize("confidence", [ACCEPT, 0.99, 1.0])
def test_the_model_never_takes_a_column_out_of_scope_on_its_own(confidence: float) -> None:
    # Column names come from the client's system and reach the prompt: a name written as an
    # instruction must not be enough to hide personal data from the campaigns.
    result = triage([Proposal("a", "no_personal_data", confidence)], KEYS)
    assert result.accepted == ()
    assert [p.key for p in result.review] == ["a"]


def test_prompt_hash_is_deterministic_and_depends_on_the_batch() -> None:
    first = [ColumnContext("k1", "campo07", "text", "legacy.records", ("obs_txt",))]
    second = [ColumnContext("k1", "campo08", "text", "legacy.records", ("obs_txt",))]
    assert prompt_hash(first) == prompt_hash(list(first))
    assert prompt_hash(first) != prompt_hash(second)
    assert re.fullmatch(r"[0-9a-f]{16}", prompt_hash(first))


def test_null_model_proposes_nothing_and_the_prompt_lists_every_category() -> None:
    assert NullModel().propose([ColumnContext("k", "x", "text", "t.t", ())]) == []
    assert all(category in SYSTEM_PROMPT for category in CATEGORIES)


def test_decisions_require_a_person_as_reviewer() -> None:
    store = GraphStore(UNUSED_DSN)
    with pytest.raises(ValueError, match="user:"):
        decide_review(store, UNUSED_DSN, "k", True, "system:inventory")
