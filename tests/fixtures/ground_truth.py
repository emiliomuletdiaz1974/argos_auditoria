"""Hand-maintained ground truth of the Phase 3 inventory (F03-00)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

GROUND_TRUTH_FILE = Path(__file__).with_name("inventory_ground_truth.yaml")
CATEGORIES = frozenset(
    {
        "personal_data",
        "special_category.health",
        "special_category.other",
        "official_identifier",
        "financial_data",
        "contact_data",
        "location_data",
        "technical_credential",
        "no_personal_data",
    }
)
DELTA_KINDS = frozenset({"appeared", "disappeared", "anomalous_growth"})


@dataclass(frozen=True, slots=True)
class ExpectedClassification:
    system: str
    column: str  # schema.table.column
    category: str
    method: str


@dataclass(frozen=True, slots=True)
class ExpectedFlow:
    source: str
    target: str
    method: str
    undirected: bool
    min_confidence: float = 0.0
    max_confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class ExpectedAiCandidate:
    system: str
    signal_kind: str
    detail_contains: str


@dataclass(frozen=True, slots=True)
class ExpectedDelta:
    system: str
    kind: str
    label: str
    qualified_name: str


@dataclass(frozen=True, slots=True)
class ProvokedChange:
    system: str
    owner_dsn: str
    sql: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroundTruth:
    systems: dict[str, dict[str, Any]]
    classifications: tuple[ExpectedClassification, ...]
    unclassified: tuple[tuple[str, str], ...]
    flows: tuple[ExpectedFlow, ...]
    ai_candidates: tuple[ExpectedAiCandidate, ...]
    provoked_changes: tuple[ProvokedChange, ...]
    expected_deltas: tuple[ExpectedDelta, ...]

    def tables(self, system: str) -> dict[str, list[str]]:
        return {str(t): list(c) for t, c in self.systems[system].get("tables", {}).items()}


def load_ground_truth(path: Path = GROUND_TRUTH_FILE) -> GroundTruth:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("version") != 1:
        raise ValueError("unsupported ground truth version")
    truth = GroundTruth(
        systems=dict(raw["systems"]),
        classifications=tuple(ExpectedClassification(**c) for c in raw["classifications"]),
        unclassified=tuple((u["system"], u["column"]) for u in raw["unclassified"]),
        flows=tuple(ExpectedFlow(**f) for f in raw["flows"]),
        ai_candidates=tuple(ExpectedAiCandidate(**a) for a in raw["ai_candidates"]),
        provoked_changes=tuple(
            ProvokedChange(system=name, owner_dsn=spec["owner_dsn"], sql=tuple(spec["sql"]))
            for name, spec in raw["provoked_changes"].items()
        ),
        expected_deltas=tuple(ExpectedDelta(**d) for d in raw["expected_deltas"]),
    )
    _check(truth)
    return truth


def _check_column(truth: GroundTruth, system: str, qualified: str) -> None:
    table, _, column = qualified.rpartition(".")
    if system not in truth.systems or column not in truth.tables(system).get(table, []):
        raise ValueError(f"unknown column in ground truth: {system} {qualified}")


def _check(truth: GroundTruth) -> None:
    for classification in truth.classifications:
        _check_column(truth, classification.system, classification.column)
        if classification.category not in CATEGORIES:
            raise ValueError(f"unknown category: {classification.category}")
    for system, column in truth.unclassified:
        _check_column(truth, system, column)
    for flow in truth.flows:
        if flow.source not in truth.systems or flow.target not in truth.systems:
            raise ValueError(f"flow between unknown systems: {flow.source} -> {flow.target}")
    for delta in truth.expected_deltas:
        if delta.kind not in DELTA_KINDS or delta.system not in truth.systems:
            raise ValueError(f"invalid expected delta: {delta}")
