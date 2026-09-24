"""ARG-100 · the release gate over the dossier of the self-verification campaign (F10-01).

A release is published with the dossier of a campaign ARGOS ran against itself. The gate reads that
dossier, not a summary: no critical or high finding, and the finding of the trap challenge present.
A campaign where the trap did not fail proves nothing — the probes did not run, or the evaluator
did not decide — so its absence blocks the release like a serious finding would.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]


def _selfcheck() -> ModuleType:
    spec = importlib.util.spec_from_file_location("selfcheck", REPO / "tools" / "selfcheck.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selfcheck = _selfcheck()


def _finding(challenge: str, severity: str) -> dict[str, Any]:
    return {
        "id": f"finding-{challenge}",
        "challenge_id": challenge,
        "obligation": "OBL-SELF-7-1",
        "severity": severity,
        "status": "open",
        "occurrences": 1,
    }


def _dossier(*findings: dict[str, Any], units: int = 6) -> dict[str, Any]:
    return {
        "schema": "argos/dossier/1",
        "campaign": {"id": "c-1", "status": "sealed"},
        "results": {"units": units, "by_result": {"compliant": units - len(findings)}},
        "findings": list(findings),
    }


TRAP = _finding("self-099", "low")


def test_only_the_trap_passes() -> None:
    assert selfcheck.gate(_dossier(TRAP)) == []


def test_a_medium_finding_does_not_block_the_release() -> None:
    assert selfcheck.gate(_dossier(TRAP, _finding("self-005", "medium"))) == []


def test_without_the_trap_the_release_is_blocked() -> None:
    reasons = selfcheck.gate(_dossier())
    assert any("self-099" in reason for reason in reasons)


@pytest.mark.parametrize("severity", ["critical", "high"])
def test_a_serious_finding_blocks_the_release(severity: str) -> None:
    reasons = selfcheck.gate(_dossier(TRAP, _finding("self-001", severity)))
    assert any("self-001" in reason and severity in reason for reason in reasons)


def test_a_trap_with_a_serious_severity_still_counts_as_serious() -> None:
    # Nobody raises the trap to high to have a release that can never be published by accident.
    reasons = selfcheck.gate(_dossier(_finding("self-099", "high")))
    assert any("high" in reason for reason in reasons)


def test_a_finding_outside_the_self_family_blocks_the_release() -> None:
    # The campaign measures ARGOS against its specification; anything else in it is a wrong scope.
    reasons = selfcheck.gate(_dossier(TRAP, _finding("sec-encryption-at-rest", "low")))
    assert any("sec-encryption-at-rest" in reason for reason in reasons)


def test_a_campaign_without_units_blocks_the_release() -> None:
    reasons = selfcheck.gate(_dossier(TRAP, units=0))
    assert any("unit" in reason for reason in reasons)


def test_a_document_that_is_not_a_dossier_is_refused() -> None:
    reasons = selfcheck.gate({**_dossier(TRAP), "schema": "argos/other/1"})
    assert any("argos/dossier/1" in reason for reason in reasons)


def test_a_campaign_that_is_not_sealed_blocks_the_release() -> None:
    dossier = _dossier(TRAP)
    dossier["campaign"]["status"] = "running"
    assert any("sealed" in reason for reason in selfcheck.gate(dossier))


def test_every_self_challenge_is_in_the_library_and_the_trap_always_fails() -> None:
    library = selfcheck.self_challenges(REPO / "library")
    assert "self-099" in library
    assert len(library) >= 6
    trap = library["self-099"]
    # The trap asks a fact that the migration fixes to one value for an answer it never has.
    assert trap["criterion"]["threshold"]["value"] != "tripped"
    assert trap["severity"] == "low"
