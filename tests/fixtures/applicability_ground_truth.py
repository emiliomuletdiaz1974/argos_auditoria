"""Hand-maintained applicability ground truth over the demo snapshot (F04-18)."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

APPLICABILITY_TRUTH_FILE = Path(__file__).with_name("applicability_ground_truth.yaml")


@dataclass(frozen=True, slots=True)
class ExpectedObligation:
    classes: tuple[str, ...]
    challenges: tuple[str, ...]


@dataclass(frozen=True, slots=True, order=True)
class ExpectedRequirement:
    obligation: str
    asset_class: str
    challenge_id: str
    nodes: frozenset[str]


@dataclass(frozen=True, slots=True)
class ApplicabilityTruth:
    systems: tuple[str, ...]
    asset_classes: dict[str, frozenset[str]]
    dates: dict[date, dict[str, ExpectedObligation]]

    def expected_plan(self, at: date) -> set[ExpectedRequirement]:
        """Plan rows the resolver must give on `at`; classes without nodes give no row."""
        return {
            ExpectedRequirement(obligation, asset_class, challenge, self.asset_classes[asset_class])
            for obligation, spec in self.dates[at].items()
            for asset_class in spec.classes
            for challenge in spec.challenges
            if self.asset_classes[asset_class]
        }


def load_applicability_truth(path: Path = APPLICABILITY_TRUTH_FILE) -> ApplicabilityTruth:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        raise ValueError("unsupported applicability ground truth version")
    systems = tuple(raw["snapshot"]["systems"])
    classes = {name: frozenset(nodes or ()) for name, nodes in raw["asset_classes"].items()}
    dates: dict[date, dict[str, ExpectedObligation]] = {}
    for at, obligations in raw["dates"].items():
        moment = at if isinstance(at, date) else date.fromisoformat(str(at))
        dates[moment] = {
            str(obligation): ExpectedObligation(
                tuple(spec["classes"]), tuple(sorted(spec["challenges"]))
            )
            for obligation, spec in obligations.items()
        }
    truth = ApplicabilityTruth(systems, classes, dates)
    _check(truth)
    return truth


def _check(truth: ApplicabilityTruth) -> None:
    for name, nodes in truth.asset_classes.items():
        for node in nodes:
            system, _, qualified = node.partition(" ")
            if system not in truth.systems or not qualified:
                raise ValueError(f"{name}: node outside the snapshot: {node!r}")
    for at, obligations in truth.dates.items():
        for obligation, spec in obligations.items():
            unknown = set(spec.classes) - set(truth.asset_classes)
            if unknown:
                raise ValueError(f"{at} {obligation}: undeclared asset classes {sorted(unknown)}")
            if not spec.challenges:
                raise ValueError(f"{at} {obligation}: an applicable obligation needs challenges")
