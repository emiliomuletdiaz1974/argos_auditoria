"""K-07 · the tools that prepare and seed the simulated sources also serve the bench.

In development they write under deploy/dev/sources and seed 127.0.0.1; in the bench the same code
runs inside the pods of bench-sources, writing to their volumes and seeding the services of the
cluster. Without arguments nothing changes for `make dev`.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def _tool(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_each_part_is_written_where_it_is_asked_and_nothing_else(tmp_path: Path) -> None:
    prepare = _tool("prepare_dev_sources")
    assert prepare.main(["--files", str(tmp_path / "files"), "--ldif", str(tmp_path / "ldif")]) == 0
    assert any((tmp_path / "files").rglob("*.pdf"))
    assert (tmp_path / "ldif" / "50-synthetic.ldif").is_file()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["files", "ldif"]


def test_the_same_tree_is_written_every_time(tmp_path: Path) -> None:
    prepare = _tool("prepare_dev_sources")
    prepare.main(["--bucket", str(tmp_path / "a")])
    prepare.main(["--bucket", str(tmp_path / "b")])
    assert prepare.tree_manifest(tmp_path / "a") == prepare.tree_manifest(tmp_path / "b")


def test_the_clinical_seed_takes_the_addresses_of_the_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARGOS_SEED_FHIR_URL", "http://source-fhir.bench-sources.svc:8080/fhir")
    monkeypatch.setenv("ARGOS_SEED_ORTHANC_URL", "http://source-dicom.bench-sources.svc:8042")
    seed = _tool("seed_dev_clinical")
    assert seed.FHIR == "http://source-fhir.bench-sources.svc:8080/fhir"
    assert seed.ORTHANC == "http://source-dicom.bench-sources.svc:8042"


def test_without_settings_the_clinical_seed_is_the_one_of_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARGOS_SEED_FHIR_URL", raising=False)
    monkeypatch.delenv("ARGOS_SEED_ORTHANC_URL", raising=False)
    seed = _tool("seed_dev_clinical")
    assert seed.FHIR == "http://127.0.0.1:8090/fhir"
    assert seed.ORTHANC == "http://127.0.0.1:8042"
