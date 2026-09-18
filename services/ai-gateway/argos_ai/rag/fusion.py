"""Reciprocal rank fusion of the two retrievals (ARG-054).

Vector and lexical search answer with scores that do not live on the same scale, so they cannot be
added. RRF does not add them: it adds positions. A fragment that both retrievals put second beats
one that only one of them put first, which is exactly the behaviour wanted — agreement is evidence.
"""

from collections.abc import Sequence
from typing import Any

# The constant of the original paper. It softens the top of the ranking: without it the first
# position would weigh so much that the second retrieval would stop mattering.
RRF_K = 60


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], k: int = RRF_K, with_scores: bool = False
) -> Any:
    """The keys of every ranking, ordered by the sum of their reciprocal positions."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1 / (k + position)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return ordered if with_scores else [key for key, _ in ordered]
