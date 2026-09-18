"""ARG-054 · the parts of the RAG that decide, without a model and without a database (F06-07).

The fusion of the two retrievals and the check of the citations. Everything that can be got wrong
silently lives here, so it can be checked against numbers worked out by hand.
"""

import pytest
from argos_ai.rag.fusion import RRF_K, reciprocal_rank_fusion
from argos_ai.rag.pipeline import (
    CitationError,
    build_context,
    checked_citations,
    refusal,
)


def test_the_fusion_prefers_what_both_retrievals_agree_on() -> None:
    """A fragment both retrievals found beats one that only one of them found, even first.

    What it does **not** do is prefer the middle: by convexity, `1/(k+1) + 1/(k+3)` is larger
    than `2/(k+2)`, so a fragment first in one list and third in the other beats one that is
    second in both. RRF rewards being found twice, not being moderate.
    """
    vector = ["solo-vectorial", "acuerdo"]
    lexical = ["otro", "acuerdo"]
    assert reciprocal_rank_fusion([vector, lexical])[0] == "acuerdo"


def test_the_fusion_score_is_the_one_of_the_formula() -> None:
    fused = reciprocal_rank_fusion([["a", "b"], ["b"]], with_scores=True)
    expected_b = 1 / (RRF_K + 2) + 1 / (RRF_K + 1)
    assert dict(fused)["b"] == pytest.approx(expected_b)
    assert dict(fused)["a"] == pytest.approx(1 / (RRF_K + 1))


def test_the_fusion_keeps_everything_either_retrieval_found() -> None:
    assert set(reciprocal_rank_fusion([["a"], ["b"]])) == {"a", "b"}


def test_the_fusion_of_nothing_is_nothing() -> None:
    assert reciprocal_rank_fusion([[], []]) == []


def test_a_citation_that_was_not_retrieved_invalidates_the_answer() -> None:
    """This is the point of the whole component: an invented citation is worse than a refusal."""
    with pytest.raises(CitationError, match="RGPD art. 99.9"):
        checked_citations([{"n": 1, "reference": "RGPD art. 99.9"}], allowed=["RGPD art. 32.1.a"])


def test_a_citation_of_a_retrieved_fragment_is_kept() -> None:
    citations = checked_citations(
        [{"n": 1, "reference": "RGPD art. 32.1.a"}], allowed=["RGPD art. 32.1.a"]
    )
    assert citations == ["RGPD art. 32.1.a"]


def test_an_answer_that_claims_to_be_sufficient_without_citing_is_refused() -> None:
    with pytest.raises(CitationError, match="sin citas"):
        checked_citations([], allowed=["RGPD art. 32.1.a"])


def test_the_context_numbers_the_fragments_so_the_prompt_can_demand_a_citation() -> None:
    context = build_context(
        [("RGPD art. 32.1.a", "la seudonimización y el cifrado"), ("RGPD art. 33.1", "72 horas")]
    )
    assert "[1] RGPD art. 32.1.a" in context
    assert "[2] RGPD art. 33.1" in context


def test_a_refusal_says_so_and_cites_nothing() -> None:
    answer = refusal(["RGPD art. 32.1.a"])
    assert answer.sufficient is False
    assert answer.citations == []
    assert "no encuentro base normativa" in answer.answer.lower()
    assert answer.nearest == ["RGPD art. 32.1.a"]
