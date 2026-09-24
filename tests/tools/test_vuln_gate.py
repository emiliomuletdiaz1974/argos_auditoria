"""ARG-087 · the vulnerability gate over the grype reports of each SBOM (F09-09).

Blocking: a critical with a fix published, or a high whose fix was first seen more than 30 days
ago (or with no date: then nobody can say it is recent). Anything else is a warning. An exception
in `platform/security/vex.yaml` lets a finding through while it has not expired; an expired
exception breaks the gate by itself, and one without justification, author or expiry does not
load.
"""

import datetime as dt
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
TODAY = dt.date(2026, 9, 23)


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("vuln_gate", REPO / "tools" / "vuln_gate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _tool()


def _match(
    cve: str, severity: str, state: str, package: str = "openssl", fixed_on: str | None = None
) -> dict[str, Any]:
    fix: dict[str, Any] = {"state": state, "versions": ["9.9.9"] if state == "fixed" else []}
    if fixed_on:
        fix["available"] = [{"version": "9.9.9", "date": fixed_on, "kind": "first-observed"}]
    return {
        "vulnerability": {"id": cve, "severity": severity, "fix": fix},
        "artifact": {"name": package, "version": "1.0.0", "type": "deb"},
    }


def _reports(tmp_path: Path, *matches: dict[str, Any], name: str = "argos-api") -> Path:
    folder = tmp_path / "sbom"
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.vulns.json").write_text(json.dumps({"matches": list(matches)}), "utf-8")
    return folder


def _vex(tmp_path: Path, *entries: dict[str, Any]) -> Path:
    path = tmp_path / "vex.yaml"
    lines = ["exceptions:"]
    for entry in entries:
        first = True
        for key, value in entry.items():
            lines.append(f"  {'- ' if first else '  '}{key}: {json.dumps(value)}")
            first = False
    if not entries:
        lines = ["exceptions: []"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(tmp_path: Path, folder: Path, vex: Path | None = None) -> Any:
    return gate.evaluate(folder, gate.load_exceptions(vex or _vex(tmp_path)), today=TODAY)


def test_a_critical_with_a_fix_blocks(tmp_path: Path) -> None:
    result = _run(tmp_path, _reports(tmp_path, _match("CVE-1", "Critical", "fixed")))
    assert [f.id for f in result.blocking] == ["CVE-1"]


def test_a_critical_without_a_fix_passes_with_a_warning(tmp_path: Path) -> None:
    result = _run(tmp_path, _reports(tmp_path, _match("CVE-1", "Critical", "not-fixed")))
    assert not result.blocking
    assert [f.id for f in result.warnings] == ["CVE-1"]


def test_a_high_with_a_fix_older_than_30_days_blocks(tmp_path: Path) -> None:
    old = _match("CVE-2", "High", "fixed", fixed_on="2026-08-01")
    recent = _match("CVE-3", "High", "fixed", fixed_on="2026-09-18")
    result = _run(tmp_path, _reports(tmp_path, old, recent))
    assert [f.id for f in result.blocking] == ["CVE-2"]
    assert [f.id for f in result.warnings] == ["CVE-3"]


def test_a_high_with_a_fix_of_unknown_date_blocks(tmp_path: Path) -> None:
    result = _run(tmp_path, _reports(tmp_path, _match("CVE-4", "High", "fixed")))
    assert [f.id for f in result.blocking] == ["CVE-4"]


def test_a_medium_never_blocks(tmp_path: Path) -> None:
    result = _run(tmp_path, _reports(tmp_path, _match("CVE-5", "Medium", "fixed")))
    assert not result.blocking and not result.warnings


def test_an_exception_in_force_lets_the_finding_through(tmp_path: Path) -> None:
    vex = _vex(
        tmp_path,
        {
            "id": "CVE-1",
            "package": "openssl",
            "justification": "not reachable: the appliance never loads the affected engine",
            "author": "equipo de plataforma",
            "expires": "2026-12-31",
        },
    )
    result = _run(tmp_path, _reports(tmp_path, _match("CVE-1", "Critical", "fixed")), vex)
    assert not result.blocking
    assert [f.id for f in result.excepted] == ["CVE-1"]


def test_an_exception_for_another_package_does_not_apply(tmp_path: Path) -> None:
    vex = _vex(
        tmp_path,
        {
            "id": "CVE-1",
            "package": "libssl3",
            "justification": "x",
            "author": "y",
            "expires": "2026-12-31",
        },
    )
    result = _run(tmp_path, _reports(tmp_path, _match("CVE-1", "Critical", "fixed")), vex)
    assert [f.id for f in result.blocking] == ["CVE-1"]


def test_an_expired_exception_breaks_the_gate_by_itself(tmp_path: Path) -> None:
    vex = _vex(
        tmp_path,
        {
            "id": "CVE-9",
            "package": "vitest",
            "justification": "development dependency",
            "author": "equipo de plataforma",
            "expires": "2026-09-01",
        },
    )
    result = _run(tmp_path, _reports(tmp_path), vex)
    assert [e.id for e in result.expired] == ["CVE-9"]
    assert not result.passed


@pytest.mark.parametrize("missing", ["justification", "author", "expires"])
def test_an_exception_without_its_reason_does_not_load(tmp_path: Path, missing: str) -> None:
    entry = {
        "id": "CVE-1",
        "package": "openssl",
        "justification": "why",
        "author": "who",
        "expires": "2026-12-31",
    }
    entry[missing] = ""
    with pytest.raises(ValueError, match=missing):
        gate.load_exceptions(_vex(tmp_path, entry))


def test_the_real_exceptions_of_the_repository_load() -> None:
    exceptions = gate.load_exceptions(REPO / "platform" / "security" / "vex.yaml")
    assert all(e.expires > TODAY for e in exceptions), "no exception is born expired"
