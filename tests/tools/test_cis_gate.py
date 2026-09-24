"""ARG-081 · the CIS gate over the report of the scanner (F09-14).

The image that does not score at least 90 % of the Level 1 Server profile, or that fails a check
nobody accepted in writing, is not published. An exception without its justification, or without
who accepted it, is an error by itself: hiding a deviation would be worse than documenting it.
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


def _gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cis_gate", REPO / "tools" / "cis_gate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _gate()


def _report(passed: int, failed: list[str], extra: int = 0) -> dict[str, Any]:
    checks = [{"id": f"9.{n}", "title": f"check {n}", "result": "pass"} for n in range(passed)]
    checks += [{"id": cid, "title": f"failed {cid}", "result": "fail"} for cid in failed]
    checks += [{"id": f"8.{n}", "title": "n/a", "result": "notapplicable"} for n in range(extra)]
    return {
        "benchmark": "CIS Ubuntu Linux 24.04 LTS",
        "profile": "Level 1 - Server",
        "checks": checks,
    }


def _exceptions(*entries: dict[str, str]) -> dict[str, Any]:
    return {"exceptions": list(entries)}


FORWARDING = {
    "id": "3.3.1",
    "title": "Ensure ip forwarding is disabled",
    "justification": "k3s routes the traffic of the pods: without forwarding there is no cluster",
    "accepted_by": "platform team, ADR-0014",
}


def _decide(report: dict[str, Any], exceptions: dict[str, Any], tmp_path: Path) -> Any:
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (tmp_path / "exceptions.yaml").write_text(yaml.safe_dump(exceptions), encoding="utf-8")
    return gate.decide(tmp_path / "report.json", tmp_path / "exceptions.yaml")


def test_89_percent_does_not_pass(tmp_path: Path) -> None:
    failed = [f"1.{n}" for n in range(11)]
    verdict = _decide(_report(89, failed), _exceptions(), tmp_path)
    assert verdict.score == pytest.approx(89.0)
    assert not verdict.passed


def test_91_percent_with_a_failure_nobody_accepted_does_not_pass(tmp_path: Path) -> None:
    failed = [f"1.{n}" for n in range(8)] + ["3.3.1"]
    verdict = _decide(_report(91, failed), _exceptions(), tmp_path)
    assert verdict.score >= 90
    assert not verdict.passed
    assert "3.3.1" in verdict.unaccepted


def test_91_percent_with_its_failures_accepted_passes(tmp_path: Path) -> None:
    failed = ["3.3.1"] + [f"1.{n}" for n in range(8)]
    accepted = [FORWARDING] + [
        {"id": f"1.{n}", "title": "t", "justification": "why", "accepted_by": "who"}
        for n in range(8)
    ]
    verdict = _decide(_report(91, failed), _exceptions(*accepted), tmp_path)
    assert verdict.passed
    assert verdict.unaccepted == []


def test_checks_that_do_not_apply_do_not_count(tmp_path: Path) -> None:
    verdict = _decide(_report(95, ["3.3.1"], extra=40), _exceptions(FORWARDING), tmp_path)
    assert verdict.score == pytest.approx(100 * 95 / 96)
    assert verdict.passed


@pytest.mark.parametrize("missing", ["justification", "accepted_by"])
def test_an_exception_without_its_reason_or_its_owner_is_an_error(
    tmp_path: Path, missing: str
) -> None:
    broken = {k: v for k, v in FORWARDING.items() if k != missing}
    with pytest.raises(gate.ExceptionsError, match=missing):
        _decide(_report(95, ["3.3.1"]), _exceptions(broken), tmp_path)


def test_a_blank_justification_is_no_justification(tmp_path: Path) -> None:
    with pytest.raises(gate.ExceptionsError, match="justification"):
        _decide(
            _report(95, ["3.3.1"]), _exceptions({**FORWARDING, "justification": "  "}), tmp_path
        )


def test_the_command_exits_non_zero_below_the_threshold(tmp_path: Path) -> None:
    (tmp_path / "report.json").write_text(
        json.dumps(_report(80, [f"1.{n}" for n in range(20)])), encoding="utf-8"
    )
    (tmp_path / "exceptions.yaml").write_text(yaml.safe_dump(_exceptions()), encoding="utf-8")
    code = gate.main(
        [
            "--report",
            str(tmp_path / "report.json"),
            "--exceptions",
            str(tmp_path / "exceptions.yaml"),
        ]
    )
    assert code == 1


def test_the_exceptions_of_the_repository_load_and_each_one_has_its_reason() -> None:
    loaded = gate.load_exceptions(REPO / "platform" / "image" / "hardening-exceptions.yaml")
    assert "3.3.1" in loaded, "k3s needs ip forwarding: the exception is documented"
