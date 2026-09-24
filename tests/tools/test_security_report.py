"""F09-15 · the report of the access battery, generated from its results for the dossier."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "security_report", REPO / "tools" / "security_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _tool()
RESULTS = {
    "started": "2026-09-24T06:00:00+00:00",
    "api": "http://127.0.0.1:8000",
    "results": [
        {"category": "matrix", "case": "auditor POST /x", "expected": "403", "got": "403",
         "ok": True},
        {"category": "matrix", "case": "auditor POST /y", "expected": "403", "got": "403",
         "ok": True},
        {"category": "tokens", "case": "alg none", "expected": "401", "got": "200", "ok": False},
    ],
}  # fmt: skip


def test_the_report_says_date_commit_totals_and_every_failure(tmp_path: Path) -> None:
    source = tmp_path / "results.json"
    source.write_text(json.dumps(RESULTS), encoding="utf-8")
    text = tool.render(json.loads(source.read_text(encoding="utf-8")), commit="abc1234")
    assert "2026-09-24" in text and "`abc1234`" in text
    assert "| matrix | 2 | 2 | 0 |" in text
    assert "| tokens | 1 | 0 | 1 |" in text
    assert "alg none" in text, "a failure is listed with its case"
    assert "auditor POST /x" not in text.split("## Fallos")[1].split("## ")[0]


def test_the_report_of_a_clean_run_says_so(tmp_path: Path) -> None:
    clean = {**RESULTS, "results": RESULTS["results"][:2]}
    text = tool.render(clean, commit="abc1234")
    assert "Ningún fallo" in text
