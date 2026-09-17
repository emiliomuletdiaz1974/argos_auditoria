"""ARG-041 · the lint tool answers with an exit code, in CI and when the library loads."""

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from argos_ontology.vocabulary import LIBRARY_DIR

TOOL = Path(__file__).parents[2] / "tools" / "challenge_lint.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("challenge_lint", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_shipped_library_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert _tool().main([]) == 0
    assert "0 error(s)" in capsys.readouterr().out


def test_a_broken_challenge_fails_with_its_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = tmp_path / "library"
    shutil.copytree(LIBRARY_DIR, library)
    broken = library / "challenges" / "sec" / "sec-encryption-at-rest.yaml"
    text = broken.read_text(encoding="utf-8")
    text = text.replace("severity: critical", "severity: catastrofica")
    broken.write_text(text, encoding="utf-8")
    assert _tool().main(["--library", str(library)]) == 1
    captured = capsys.readouterr()
    assert "sec-encryption-at-rest.yaml" in captured.err
    assert "1 error(s)" in captured.out
