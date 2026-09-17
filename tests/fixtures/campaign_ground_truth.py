"""Hand-maintained campaign ground truth over the demo snapshot (F05-01)."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

CAMPAIGN_TRUTH_FILE = Path(__file__).with_name("campaign_ground_truth.yaml")
RESULTS = ("compliant", "non_compliant", "not_demonstrated", "inconclusive")
# Worst first: the aggregate of several results is the first one present in this order.
SEVERITY_ORDER = ("non_compliant", "not_demonstrated", "inconclusive", "compliant")


@dataclass(frozen=True, slots=True, order=True)
class ExpectedVerdict:
    challenge_id: str
    system: str
    result: str
    reason: str


@dataclass(frozen=True, slots=True, order=True)
class ExpectedFinding:
    challenge_id: str
    system: str
    obligation: str


@dataclass(frozen=True, slots=True, order=True)
class Unverifiable:
    challenge_id: str
    system: str
    reason: str


@dataclass(frozen=True, slots=True)
class CampaignTruth:
    campaign_date: date
    systems: tuple[str, ...]
    obligations: dict[str, str]  # challenge_id -> obligation
    verdicts: tuple[ExpectedVerdict, ...]
    unverifiable: tuple[Unverifiable, ...]
    aggregate: dict[str, str]

    @property
    def findings(self) -> tuple[ExpectedFinding, ...]:
        return tuple(
            ExpectedFinding(v.challenge_id, v.system, self.obligations[v.challenge_id])
            for v in self.verdicts
            if v.result == "non_compliant"
        )


def worst(results: list[str]) -> str:
    return next(result for result in SEVERITY_ORDER if result in results)


def load_campaign_truth(path: Path = CAMPAIGN_TRUTH_FILE) -> CampaignTruth:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        raise ValueError("unsupported campaign ground truth version")
    systems = tuple(raw["snapshot"]["systems"])
    obligations: dict[str, str] = {}
    verdicts: list[ExpectedVerdict] = []
    for challenge_id, spec in raw["challenges"].items():
        obligations[str(challenge_id)] = str(spec["obligation"])
        for system, expected in spec.items():
            if system == "obligation":
                continue
            if system not in systems:
                raise ValueError(f"{challenge_id}: system outside the snapshot: {system}")
            if expected["result"] not in RESULTS:
                raise ValueError(f"{challenge_id} {system}: unknown result {expected['result']!r}")
            if not str(expected.get("reason", "")).strip():
                raise ValueError(f"{challenge_id} {system}: every expectation needs its reason")
            verdicts.append(
                ExpectedVerdict(str(challenge_id), system, expected["result"], expected["reason"])
            )
    unverifiable = tuple(
        Unverifiable(str(u["challenge"]), str(u["system"]), str(u["reason"]))
        for u in raw.get("unverifiable", [])
    )
    moment = raw["campaign_date"]
    truth = CampaignTruth(
        campaign_date=moment if isinstance(moment, date) else date.fromisoformat(str(moment)),
        systems=systems,
        obligations=obligations,
        verdicts=tuple(sorted(verdicts)),
        unverifiable=tuple(sorted(unverifiable)),
        aggregate={str(k): str(v) for k, v in raw["aggregate"].items()},
    )
    _check(truth)
    return truth


def _check(truth: CampaignTruth) -> None:
    seen = [(v.challenge_id, v.system) for v in truth.verdicts]
    seen += [(u.challenge_id, u.system) for u in truth.unverifiable]
    if len(seen) != len(set(seen)):
        raise ValueError("a challenge and system appear more than once")
    for system in truth.systems:
        results = [v.result for v in truth.verdicts if v.system == system]
        if truth.aggregate.get(system) != worst(results):
            raise ValueError(f"aggregate of {system} is not the worst of its results")
