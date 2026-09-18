"""ARG-063 · merkle.py travels with the record as a standalone verifier."""

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from argos_evidence import merkle
from argos_evidence.merkle import build_tree, proof

MODULE = Path(merkle.__file__)


def test_it_imports_only_the_standard_library() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports: the file ships alone"
            imported.add((node.module or "").split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}


def _proof_file(tmp_path: Path, artifact: bytes, index: int, root: str | None = None) -> Path:
    artifacts = [hashlib.sha256(f"other-{i}".encode()).digest() for i in range(5)]
    artifacts[index] = hashlib.sha256(artifact).digest()
    tree = build_tree(artifacts)
    document = {
        "index": index,
        "size": tree.size,
        "path": [[side, sibling.hex()] for side, sibling in proof(tree, index)],
        "root": root or tree.root.hex(),
    }
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _run(*args: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and our own file
        [sys.executable, str(MODULE), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_standalone_run_accepts_an_intact_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(b'{"verdict":"compliant"}')
    result = _run(artifact, _proof_file(tmp_path, artifact.read_bytes(), 3))
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_the_standalone_run_rejects_a_changed_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    proof_path = _proof_file(tmp_path, b'{"verdict":"compliant"}', 3)
    artifact.write_bytes(b'{"verdict":"compliant "}')
    result = _run(artifact, proof_path)
    assert result.returncode == 1
    assert "FAIL" in result.stdout
