"""Calibration: turning a declared confidence into one that means what it says (ARG-055).

Models state confidences they do not earn: they say 0.9 and are right 0.7 of the time. Without a
correction the thresholds of ARG-025 —accept at 0.85, review from 0.50— would be arbitrary numbers.

The correction learns from the client without training anything. Every decision of the DPO in the
review queue is a free label: the model declared a confidence, the human said right or wrong. An
isotonic regression over those pairs, one per category, maps what the model declares to what it
has actually achieved. Isotonic, because the only thing assumed is that a higher declared
confidence should never mean a lower real one.

With fewer than `MINIMUM_PAIRS` decisions in a category there is no curve to trust, and there is no
reason to trust the model either: the calibration is the identity, capped at `UNTRUSTED_CEILING`.
That ceiling sits below the acceptance threshold on purpose — an uncalibrated model can fill the
review queue, but it cannot classify anything alone.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

MINIMUM_PAIRS = 50
UNTRUSTED_CEILING = 0.8
DRIFT_WINDOW_DAYS = 30

Block = tuple[float, float]  # (smallest declared confidence of the block, calibrated value)


@dataclass(frozen=True, slots=True)
class Decision:
    """One resolution of the review queue: what the model declared and whether it was right."""

    category: str
    declared: float
    right: bool
    decided_at: datetime


def isotonic_blocks(pairs: Iterable[tuple[float, int]]) -> list[Block]:
    """Pool adjacent violators: the non-decreasing step function closest to the data.

    Each block keeps the smallest declared confidence it covers and the mean hit rate of its
    pairs. Two neighbours that break the order are merged until none does.
    """
    # Equal declared confidences are one point with one value. Sorting the raw pairs would put
    # the misses before the hits of the same confidence and read that as a rising curve.
    grouped: dict[float, list[float]] = {}
    for declared, hit in pairs:
        entry = grouped.setdefault(declared, [0.0, 0.0])
        entry[0] += hit
        entry[1] += 1
    blocks: list[list[float]] = []  # [start, sum of hits, count]
    for declared in sorted(grouped):
        hits, count = grouped[declared]
        blocks.append([declared, hits, count])
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] > blocks[-1][1] / blocks[-1][2]:
            start, hits, count = blocks.pop()
            blocks[-1][1] += hits
            blocks[-1][2] += count
    merged: list[Block] = []
    for start, hits, count in blocks:
        value = hits / count
        if merged and merged[-1][1] == value:
            continue
        merged.append((start, value))
    return merged


def _step(blocks: Sequence[Block], declared: float) -> float:
    """The value of the block a declared confidence falls in; below the first, the first."""
    value = blocks[0][1]
    for start, block_value in blocks:
        if declared < start:
            break
        value = block_value
    return value


class Calibrator:
    """One isotonic curve per category, or the capped identity where there is no curve yet."""

    def __init__(self, curves: Mapping[str, Sequence[Block]]) -> None:
        self._curves = {category: list(blocks) for category, blocks in curves.items() if blocks}

    @classmethod
    def fit(cls, decisions: Iterable[Decision]) -> "Calibrator":
        by_category: dict[str, list[tuple[float, int]]] = {}
        for decision in decisions:
            pair = (decision.declared, int(decision.right))
            by_category.setdefault(decision.category, []).append(pair)
        curves = {
            category: isotonic_blocks(pairs)
            for category, pairs in by_category.items()
            if len(pairs) >= MINIMUM_PAIRS
        }
        return cls(curves)

    @classmethod
    def from_curves(cls, curves: Mapping[str, Sequence[Sequence[float]]]) -> "Calibrator":
        return cls(
            {
                category: [(float(start), float(value)) for start, value in blocks]
                for category, blocks in curves.items()
            }
        )

    def curves(self) -> dict[str, list[list[float]]]:
        """The curves as plain lists, ready to be stored as JSON and read back identical."""
        return {
            category: [[start, value] for start, value in blocks]
            for category, blocks in self._curves.items()
        }

    def calibrate(self, category: str, declared: float) -> float:
        blocks = self._curves.get(category)
        if blocks is None:
            return min(declared, UNTRUSTED_CEILING)
        return _step(blocks, declared)


def precision_by_category(
    decisions: Iterable[Decision],
    now: datetime | None = None,
    window_days: int = DRIFT_WINDOW_DAYS,
) -> dict[str, float]:
    """The drift metric for ARG-059: how often the model was right, per category, lately."""
    moment = now or datetime.now(UTC)
    since = moment - timedelta(days=window_days)
    hits: dict[str, list[int]] = {}
    for decision in decisions:
        if decision.decided_at < since:
            continue
        hits.setdefault(decision.category, []).append(int(decision.right))
    return {category: sum(values) / len(values) for category, values in hits.items()}


def decision_from_row(row: Sequence[Any]) -> Decision:
    """(proposed_category, confidence, status, decided_at) of the review queue, as a decision."""
    category, confidence, status, decided_at = row
    return Decision(str(category), float(confidence), str(status) == "accepted", decided_at)
