"""The hand-maintained inventory ground truth is internally consistent (F03-00)."""

import json
from pathlib import Path

import pytest

from fixtures.ground_truth import CATEGORIES, DELTA_KINDS, GROUND_TRUTH_FILE, load_ground_truth

CATALOG = Path(__file__).parents[2] / "deploy" / "dev" / "sources" / "systems.json"


def _catalog() -> dict[str, dict[str, object]]:
    systems = json.loads(CATALOG.read_text(encoding="utf-8"))["systems"]
    return {s["name"]: s for s in systems}


def test_describes_exactly_the_sources_profile() -> None:
    truth = load_ground_truth()
    catalog = _catalog()
    sources = {name for name, s in catalog.items() if s["profile"] == "sources"}
    assert set(truth.systems) == sources
    for name, spec in truth.systems.items():
        assert catalog[name]["kind"] == spec["kind"], name


def test_categories_and_delta_kinds_are_closed_lists() -> None:
    truth = load_ground_truth()
    assert {c.category for c in truth.classifications} <= CATEGORIES
    assert {d.kind for d in truth.expected_deltas} == DELTA_KINDS


def test_structural_pair_shares_its_classified_signature() -> None:
    truth = load_ground_truth()

    def signature(system: str, table: str) -> set[tuple[str, str]]:
        return {
            (c.column.rsplit(".", 1)[1], c.category)
            for c in truth.classifications
            if c.system == system and c.column.rsplit(".", 1)[0] == table
        }

    postgres = signature("dev-source-postgres", "clinic.patient_documents")
    mariadb = signature("dev-source-mariadb", "billing.patient_mirror")
    # Same rule as the structural detector (ARG-027): at least 4 shared pairs and Jaccard >= 0.8.
    # clinic.patient_documents also classifies its patient_id; billing.patient_mirror has none.
    assert len(postgres & mariadb) >= 4
    assert len(postgres & mariadb) / len(postgres | mariadb) >= 0.8
    assert any(category.startswith("special_category") for _, category in postgres)


def test_rejects_a_classification_on_an_unknown_column(tmp_path: Path) -> None:
    text = GROUND_TRUTH_FILE.read_text(encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text(text.replace("clinic.patients.full_name", "clinic.patients.nope", 1), "utf-8")
    with pytest.raises(ValueError, match="unknown column"):
        load_ground_truth(bad)
