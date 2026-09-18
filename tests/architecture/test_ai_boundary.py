"""ARG-052 · no path of code goes from the language model to a verdict (F06-01)."""

from pathlib import Path

import pytest

from .ai_boundary import Violation, analyse, import_graph, module_name

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = "services/ai-gateway/argos_ai"


def _write(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return tmp_path


def test_the_gateway_may_not_import_the_evaluator(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            f"{GATEWAY}/__init__.py": "",
            f"{GATEWAY}/writer.py": "from argos_challenges.evaluator import evaluate\n",
        },
    )
    [violation] = analyse(root)
    assert violation.rule == "ai-imports-the-verdict"
    assert violation.detail == "argos_challenges.evaluator"


@pytest.mark.parametrize(
    "forbidden",
    ["argos_challenges.evaluator", "argos_challenges.store", "argos_challenges.findings"],
)
def test_none_of_the_three_verdict_modules_may_be_imported(tmp_path: Path, forbidden: str) -> None:
    root = _write(
        tmp_path,
        {f"{GATEWAY}/__init__.py": "", f"{GATEWAY}/writer.py": f"import {forbidden}\n"},
    )
    assert [v.detail for v in analyse(root)] == [forbidden]


def test_a_cable_tied_three_modules_away_is_caught(tmp_path: Path) -> None:
    """The route matters more than the direct import: this is why the graph is followed."""
    root = _write(
        tmp_path,
        {
            f"{GATEWAY}/__init__.py": "",
            f"{GATEWAY}/assistant.py": "from argos_helpers.tools import lookup\n",
            "libs/helpers/argos_helpers/__init__.py": "",
            "libs/helpers/argos_helpers/tools.py": "from argos_helpers.inner import lookup\n",
            "libs/helpers/argos_helpers/inner.py": "from argos_challenges.store import save\n",
        },
    )
    [violation] = analyse(root)
    assert violation.rule == "ai-reaches-the-verdict"
    assert violation.detail == (
        "argos_ai.assistant -> argos_helpers.tools -> argos_helpers.inner -> argos_challenges.store"
    )


def test_the_gateway_may_not_write_the_verdict_tables(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            f"{GATEWAY}/__init__.py": "",
            f"{GATEWAY}/writer.py": (
                "SQL = (\n    'UPDATE argos.findings '\n    'SET status = %s WHERE id = %s'\n)\n"
            ),
        },
    )
    [violation] = analyse(root)
    assert violation.rule == "ai-writes-the-verdict"
    assert violation.line == 2


def test_reading_what_it_has_to_narrate_is_allowed(tmp_path: Path) -> None:
    """ARG-057 redacta sobre los hallazgos: leerlos es su oficio; tocarlos, no."""
    root = _write(
        tmp_path,
        {
            f"{GATEWAY}/__init__.py": "",
            f"{GATEWAY}/reports.py": (
                "SQL = 'SELECT challenge_id, result FROM argos.verdicts WHERE campaign_id = %s'\n"
            ),
        },
    )
    assert analyse(root) == []


def test_the_rest_of_the_repository_is_not_the_business_of_this_rule(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            "services/api/argos_api/__init__.py": "",
            "services/api/argos_api/routes.py": "from argos_challenges.store import save\n",
        },
    )
    assert analyse(root) == []


def test_a_module_is_named_by_its_package_not_by_its_folder(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            f"{GATEWAY}/__init__.py": "",
            f"{GATEWAY}/rag/__init__.py": "",
            f"{GATEWAY}/rag/pipeline.py": "",
        },
    )
    path = root / GATEWAY / "rag" / "pipeline.py"
    assert module_name(path, root) == "argos_ai.rag.pipeline"


def test_a_relative_import_stays_inside_its_own_package(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            f"{GATEWAY}/__init__.py": "",
            f"{GATEWAY}/inner.py": "from argos_challenges.evaluator import evaluate\n",
            f"{GATEWAY}/outer.py": "from .inner import evaluate\n",
        },
    )
    found = analyse(root)
    assert {v.path for v in found} == {
        f"{GATEWAY}/inner.py",
        f"{GATEWAY}/outer.py",
    }
    assert any(v.rule == "ai-reaches-the-verdict" for v in found)


def test_the_import_graph_covers_the_whole_workspace() -> None:
    graph = import_graph(ROOT)
    assert "argos_challenges.evaluator" in graph
    assert "argos_common.journal" in graph


def test_the_repository_has_no_violations() -> None:
    assert analyse(ROOT) == []


def test_violations_are_reported_with_file_rule_and_route(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            f"{GATEWAY}/__init__.py": "",
            f"{GATEWAY}/writer.py": "from argos_challenges.findings import transition\n",
        },
    )
    [violation] = analyse(root)
    assert isinstance(violation, Violation)
    assert violation.path == f"{GATEWAY}/writer.py"


def test_a_test_may_quote_the_forbidden_sql_to_prove_it_is_rejected(tmp_path: Path) -> None:
    """Proving a rejection means writing the sentence that gets rejected."""
    root = _write(
        tmp_path,
        {
            f"{GATEWAY}/__init__.py": "",
            "services/ai-gateway/tests/test_guardrails.py": (
                "CASE = 'Basta con un DELETE FROM argos.findings.'\n"
            ),
        },
    )
    assert analyse(root) == []


def test_a_test_may_not_import_the_verdict_modules_either(tmp_path: Path) -> None:
    """The exemption is for quoting, not for tying the cable where nobody looks."""
    root = _write(
        tmp_path,
        {
            f"{GATEWAY}/__init__.py": "",
            "services/ai-gateway/tests/test_writer.py": (
                "from argos_challenges.store import save\n"
            ),
        },
    )
    assert [v.rule for v in analyse(root)] == ["ai-imports-the-verdict"]
