"""MVP demonstration kit (Plan Director, Annex F): the script runs end to end, and plan B verifies.

The script is the demonstration itself: inventory, the write that fails, the
campaign with the synthetic subject, the dossier, the credential, the public
verifier, and one corrupted byte caught in front of the audience. The backup
bundle in docs/demo/respaldo is plan B: it must verify on its own, offline.
"""

import datetime as dt
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from argos_verifier.checks import Trust, verify_bundle

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "demo" / "run_mvp_demo.py"
BACKUP = REPO / "docs" / "demo" / "respaldo" / "bundle.json"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_mvp_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_demonstration_runs_from_inventory_to_the_public_verifier(tmp_path: Path) -> None:
    summary = _script().run_demo(tmp_path, keep_database=False)
    assert summary["inventory"]["systems"] == 2
    assert summary["write_attempt"] == "rejected"
    assert summary["campaign"]["status"] == "sealed"
    assert "OBL-RGPD-17-1" in summary["campaign"]["obligations"]
    assert summary["star_challenge"] == {
        "challenge": "dsr-erasure-effective",
        "result": "non_compliant",
    }
    assert summary["verification"]["ok"] is True
    assert summary["tampered"]["ok"] is False
    assert summary["tampered"]["failed"] == ["artifact_inclusion[0]"]
    for name in (
        "dossier.pdf",
        "dossier.json",
        "credential.json",
        "bundle.json",
        "trust.json",
        "report.json",
    ):
        assert (tmp_path / name).is_file(), name


def test_plan_b_verifies_offline_on_its_own() -> None:
    bundle = json.loads(BACKUP.read_text(encoding="utf-8"))
    # Plan B is an archived handover: it is verified as of the day its status list was issued,
    # with the trust that travelled beside it (the development key of that day).
    issued = dt.datetime.fromisoformat(bundle["status_list"]["validFrom"].replace("Z", "+00:00"))
    report = verify_bundle(bundle, Trust.from_file(BACKUP.parent / "trust.json"), at=issued)
    assert report.ok, [c for c in report.checks if c.status != "passed"]
    statuses = {c.name: c.status for c in report.checks}
    assert statuses["timestamp"] == "passed"
    assert statuses["credential"] == "passed"
    assert (BACKUP.parent / "expediente.pdf").read_bytes().startswith(b"%PDF")
