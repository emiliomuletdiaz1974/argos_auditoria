"""Decisions of a synthetic DPO over the demo snapshot (F04-23).

They go through the real Phase 3 mechanisms: a scripted model proposes `no_personal_data` with a
review confidence, `decide_review` accepts it, and `confirm_ai_system` confirms AI candidates. Both
leave their entries in the journal, exactly as a person using the console would.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from argos_inventory.ai_discovery.detect import confirm_ai_system
from argos_inventory.classify.assisted import (
    ColumnContext,
    Proposal,
    classify_grey_zone,
    decide_review,
)
from argos_inventory.graph.model import ai_system_key
from argos_inventory.graph.store import GraphStore

DEMO_REVIEW_FILE = Path(__file__).with_name("demo_review.yaml")
REVIEW_CONFIDENCE = 0.6  # between the review (0.50) and accept (0.85) thresholds


@dataclass(frozen=True, slots=True)
class ConfirmedAi:
    system: str
    name: str
    purpose: str
    risk_class: str


@dataclass(frozen=True, slots=True)
class DemoReview:
    reviewer: str
    no_personal_data: dict[str, tuple[str, ...]]
    ai_systems: tuple[ConfirmedAi, ...]


def load_demo_review(path: Path = DEMO_REVIEW_FILE) -> DemoReview:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        raise ValueError("unsupported demo review version")
    reviewer = str(raw["reviewer"])
    if not reviewer.startswith("user:"):
        raise ValueError("demo decisions are taken by a person: reviewer must be user:<sub>")
    return DemoReview(
        reviewer=reviewer,
        no_personal_data={
            str(system): tuple(sorted(columns))
            for system, columns in raw["no_personal_data"].items()
        },
        ai_systems=tuple(ConfirmedAi(**entry) for entry in raw["ai_systems"]),
    )


class ScriptedModel:
    """Proposes `no_personal_data` for the reviewed columns of one system, nothing else."""

    def __init__(self, columns: Sequence[str]) -> None:
        self._columns = frozenset(columns)
        self.proposed: list[str] = []

    def propose(self, columns: Sequence[ColumnContext]) -> list[Proposal]:
        proposals = [
            Proposal(c.key, "no_personal_data", REVIEW_CONFIDENCE, "technical column")
            for c in columns
            if f"{c.table}.{c.name}" in self._columns
        ]
        self.proposed.extend(p.key for p in proposals)
        return proposals


def apply_demo_review(
    store: GraphStore,
    dsn: str,
    system_ids: Mapping[str, str],
    review: DemoReview | None = None,
) -> None:
    """Queue and accept the column decisions, then confirm the AI systems, as the synthetic DPO."""
    decisions = review or load_demo_review()
    for system, columns in decisions.no_personal_data.items():
        model = ScriptedModel(columns)
        summary = classify_grey_zone(store, dsn, model, system_ids[system])
        if summary.queued != len(columns):
            raise RuntimeError(f"{system}: queued {summary.queued} of {len(columns)} decisions")
        for key in model.proposed:
            decide_review(store, dsn, key, True, decisions.reviewer)
    for ai in decisions.ai_systems:
        key = ai_system_key(system_ids[ai.system], ai.name)
        confirm_ai_system(store, dsn, key, decisions.reviewer, ai.purpose, ai.risk_class)
