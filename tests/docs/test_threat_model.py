"""The threat model is a product document: every mitigation must be traceable and honest."""

import re
from pathlib import Path

import pytest

Mitigations = list[dict[str, str]]

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "docs" / "seguridad" / "modelo-amenazas.md"

STATUSES = {"implementada", "en desarrollo", "pendiente de hardware"}
PHASE9_COMPONENTS = {f"ARG-{n:03d}" for n in range(81, 91)}
COMPONENT = re.compile(r"ARG-\d{3}")
TASK = re.compile(r"\b(?:F\d{2}-\d{2}[a-z]?|F1-\d{2}[ab]?)\b")
PATH = re.compile(r"`([^`]+)`")


def _rows(id_pattern: str) -> list[list[str]]:
    row_id = re.compile(rf"\| {id_pattern} \|")
    rows = []
    for line in MODEL.read_text(encoding="utf-8").splitlines():
        if row_id.match(line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


@pytest.fixture(scope="module")
def adversaries() -> dict[str, str]:
    return {row[0]: row[1] for row in _rows(r"A\d+")}


@pytest.fixture(scope="module")
def mitigations() -> Mitigations:
    keys = (
        "id",
        "threat",
        "surface",
        "adversaries",
        "mitigation",
        "component",
        "task",
        "status",
        "evidence",
    )
    return [dict(zip(keys, row, strict=True)) for row in _rows(r"M-\d+")]


def test_model_exists() -> None:
    assert MODEL.is_file(), "docs/seguridad/modelo-amenazas.md is missing"


def test_every_mitigation_names_a_component_and_a_valid_status(mitigations: Mitigations) -> None:
    assert mitigations, "no mitigation rows found"
    for m in mitigations:
        assert COMPONENT.search(m["component"]), f"{m['id']}: no ARG-NNN component"
        assert m["task"] == "—" or TASK.search(m["task"]), f"{m['id']}: task is not a plan task id"
        assert m["status"] in STATUSES, f"{m['id']}: unknown status {m['status']!r}"


def test_mitigation_ids_are_unique(mitigations: Mitigations) -> None:
    ids = [m["id"] for m in mitigations]
    assert len(ids) == len(set(ids))


def test_every_phase9_component_is_covered(mitigations: Mitigations) -> None:
    cited = {c for m in mitigations for c in COMPONENT.findall(m["component"])}
    assert cited >= PHASE9_COMPONENTS, f"missing: {sorted(PHASE9_COMPONENTS - cited)}"


def test_every_adversary_has_a_mitigation(
    adversaries: dict[str, str], mitigations: Mitigations
) -> None:
    assert adversaries, "no adversary rows found"
    covered = {a.strip() for m in mitigations for a in m["adversaries"].split(",")}
    assert set(adversaries) <= covered, f"uncovered: {sorted(set(adversaries) - covered)}"
    assert covered <= set(adversaries), f"unknown adversaries: {sorted(covered - set(adversaries))}"


def test_implemented_mitigations_point_to_existing_evidence(mitigations: Mitigations) -> None:
    for m in mitigations:
        if m["status"] != "implementada":
            continue
        paths = PATH.findall(m["evidence"])
        assert paths, f"{m['id']}: implemented without evidence"
        for p in paths:
            assert (ROOT / p).exists(), f"{m['id']}: evidence {p} does not exist"
