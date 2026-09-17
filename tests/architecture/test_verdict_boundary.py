"""ARG-046 · nothing outside the evaluator produces a verdict (F05-04)."""

from pathlib import Path

import pytest

from .verdict_boundary import EVALUATOR_FILE, STORE_FILE, Violation, analyse

ROOT = Path(__file__).resolve().parents[2]
PLANTED = {
    "builds_a_verdict.py": "from argos_challenges.evaluator import Verdict\n\nv = Verdict()\n",
    "builds_it_with_an_alias.py": (
        "from argos_challenges.evaluator import Verdict as V\n\nv = V(result='compliant')\n"
    ),
    "builds_it_through_the_module.py": (
        "from argos_challenges import evaluator as ev\n\nv = ev.Verdict()\n"
    ),
    "hides_it_behind_a_star_import.py": "from argos_challenges.evaluator import *\n",
    "writes_the_verdicts_table.py": (
        "SQL = 'INSERT INTO argos.verdicts (id, result) VALUES (%s, %s)'\n"
    ),
    "deletes_verdicts_in_pieces.py": (
        "SQL = (\n    'DELETE FROM argos.verdicts '\n    'WHERE campaign_id = %s'\n)\n"
    ),
}
ALLOWED = {
    "reads_the_verdicts_table.py": "SQL = 'SELECT result FROM argos.verdicts WHERE id = %s'\n",
    "reads_a_verdict_type.py": (
        "from argos_challenges.evaluator import Verdict\n\n"
        "def persist(v: Verdict) -> str:\n    return v.hash\n"
    ),
}


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    package = tmp_path / "services" / "fake"
    package.mkdir(parents=True)
    for name, source in files.items():
        (package / name).write_text(source, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(("name", "source"), sorted(PLANTED.items()))
def test_planted_breaches_are_detected(tmp_path: Path, name: str, source: str) -> None:
    root = _write(tmp_path, {name: source})
    found = analyse(root)
    assert [v.path for v in found] == [f"services/fake/{name}"], found
    assert found[0].rule in {"verdict-outside-evaluator", "verdict-sql-outside-store"}


@pytest.mark.parametrize(("name", "source"), sorted(ALLOWED.items()))
def test_reading_verdicts_is_allowed(tmp_path: Path, name: str, source: str) -> None:
    assert analyse(_write(tmp_path, {name: source})) == []


def test_the_evaluator_may_not_import_a_language_model(tmp_path: Path) -> None:
    evaluator = tmp_path / EVALUATOR_FILE
    evaluator.parent.mkdir(parents=True)
    evaluator.write_text("import openai\nfrom torch import nn\n", encoding="utf-8")
    rules = {v.rule for v in analyse(tmp_path)}
    assert rules == {"ai-import-in-evaluator"}


def test_the_evaluator_and_the_store_keep_their_privileges(tmp_path: Path) -> None:
    evaluator = tmp_path / EVALUATOR_FILE
    evaluator.parent.mkdir(parents=True)
    evaluator.write_text(
        "class Verdict:\n    pass\n\n\ndef evaluate() -> Verdict:\n    return Verdict()\n",
        encoding="utf-8",
    )
    store = tmp_path / STORE_FILE
    store.write_text("SQL = 'INSERT INTO argos.verdicts (id) VALUES (%s)'\n", encoding="utf-8")
    assert analyse(tmp_path) == []


def test_the_repository_has_no_violations() -> None:
    assert analyse(ROOT) == []


def test_violations_are_reported_with_file_line_and_rule(tmp_path: Path) -> None:
    root = _write(
        tmp_path, {"writes_the_verdicts_table.py": PLANTED["writes_the_verdicts_table.py"]}
    )
    [violation] = analyse(root)
    assert isinstance(violation, Violation)
    assert violation.line == 1 and violation.detail == "argos.verdicts"
