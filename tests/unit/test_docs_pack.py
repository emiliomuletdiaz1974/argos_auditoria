"""Technical documentation: coverage check and client documentation packs (D-01)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

TOOL = Path(__file__).parents[2] / "tools" / "docs_pack.py"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("docs_pack", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


docs_pack = _tool()


def _doc(kind: str, doc_id: str, confidentiality: str = "client", **extra: str) -> str:
    fields = {
        "id": doc_id,
        "kind": kind,
        "title": f"Título {doc_id}",
        "version": "0.1.0",
        "commit": "abc1234",
        "date": "2026-09-17",
        "status": "current",
        "confidentiality": confidentiality,
        **extra,
    }
    header = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return f"---\n{header}\n---\n\n# {fields['title']}\n\nContenido con tildes: ñ á.\n"


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "libs" / "common").mkdir(parents=True)
    (root / "libs" / "common" / "pyproject.toml").write_text(
        '[project]\nname = "argos-common"\n', encoding="utf-8"
    )
    (root / "services" / "inventory").mkdir(parents=True)
    (root / "services" / "inventory" / "pyproject.toml").write_text(
        '[project]\nname = "argos-inventory"\n', encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["libs/common", "services/inventory"]\n', encoding="utf-8"
    )
    (root / "docs" / "fases").mkdir(parents=True)
    (root / "docs" / "fases" / "interfaces-F03.md").write_text("# F03\n", encoding="utf-8")
    tech = root / "docs" / "tecnica"
    (tech / "modulos").mkdir(parents=True)
    (tech / "fases").mkdir(parents=True)
    (tech / "modulos" / "argos-common.md").write_text(
        _doc("module", "MOD-argos-common", module="argos-common", phases='["01", "03"]'),
        encoding="utf-8",
    )
    (tech / "modulos" / "argos-inventory.md").write_text(
        _doc("module", "MOD-argos-inventory", module="argos-inventory", phases='["03"]'),
        encoding="utf-8",
    )
    (tech / "fases" / "F03-inventario-grafo.md").write_text(
        _doc("phase", "FASE-03", phase='"03"'), encoding="utf-8"
    )
    (tech / "README.md").write_text(
        "# Documentación técnica\n\n"
        "- [argos-common](modulos/argos-common.md)\n"
        "- [argos-inventory](modulos/argos-inventory.md)\n"
        "- [Fase 03](fases/F03-inventario-grafo.md)\n",
        encoding="utf-8",
    )
    return root


def test_a_complete_repository_has_no_coverage_errors(tmp_path: Path) -> None:
    assert docs_pack.coverage_errors(_repo(tmp_path)) == []


def test_modules_come_from_the_uv_workspace(tmp_path: Path) -> None:
    assert docs_pack.workspace_modules(_repo(tmp_path)) == ["argos-common", "argos-inventory"]


def test_a_workspace_module_without_document_is_an_error(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "docs" / "tecnica" / "modulos" / "argos-inventory.md").unlink()
    errors = docs_pack.coverage_errors(root)
    assert any("argos-inventory" in e and "no module document" in e for e in errors)


def test_a_closed_phase_without_closure_document_is_an_error(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "docs" / "fases" / "interfaces-F04.md").write_text("# F04\n", encoding="utf-8")
    assert "phase 04 is closed but has no closure document" in docs_pack.coverage_errors(root)


def test_documents_missing_from_the_index_are_errors(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "docs" / "tecnica" / "README.md").write_text("# Índice\n", encoding="utf-8")
    assert len(docs_pack.coverage_errors(root)) == 3


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("# sin cabecera\n", "front matter"),
        ("---\nid: X\nkind: phase\n---\n", "missing"),
        (_doc("phase", "FASE-x", confidentiality="secret", phase="01"), "confidentiality"),
        (_doc("widget", "MOD-x"), "kind"),
    ],
)
def test_invalid_front_matter_is_rejected(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "doc.md"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        docs_pack.parse_doc(path)


def test_selection_by_phase_takes_its_closure_and_its_modules(tmp_path: Path) -> None:
    docs = docs_pack.load_docs(_repo(tmp_path))
    selected = docs_pack.select_docs(docs, phases=["03"], modules=[], include_internal=False)
    ids = [d.meta["id"] for d in selected]
    assert ids == ["FASE-03", "MOD-argos-common", "MOD-argos-inventory"]
    only_01 = docs_pack.select_docs(docs, phases=["01"], modules=[], include_internal=False)
    assert [d.meta["id"] for d in only_01] == ["MOD-argos-common"]


def test_internal_documents_are_left_out_unless_asked(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "docs" / "tecnica" / "modulos" / "argos-common.md").write_text(
        _doc("module", "MOD-argos-common", "internal", module="argos-common", phases='["03"]'),
        encoding="utf-8",
    )
    docs = docs_pack.load_docs(root)
    public = docs_pack.select_docs(docs, phases=["03"], modules=[], include_internal=False)
    everything = docs_pack.select_docs(docs, phases=["03"], modules=[], include_internal=True)
    assert "MOD-argos-common" not in [d.meta["id"] for d in public]
    assert "MOD-argos-common" in [d.meta["id"] for d in everything]


def test_a_pack_has_documents_index_and_manifest_with_hashes(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    docs = docs_pack.select_docs(
        docs_pack.load_docs(root), phases=[], modules=["argos-inventory"], include_internal=False
    )
    pack = docs_pack.build_pack(docs, tmp_path / "out", "cliente-demo", "2026-09-17", pdf=False)
    assert pack.name == "2026-09-17-cliente-demo"
    assert sorted(p.name for p in pack.iterdir()) == [
        "INDICE.md",
        "MOD-argos-inventory.md",
        "manifest.json",
    ]
    body = (pack / "MOD-argos-inventory.md").read_text(encoding="utf-8")
    assert not body.startswith("---") and "| Versión | 0.1.0 |" in body
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["label"] == "cliente-demo"
    assert set(manifest["files"]) == {"INDICE.md", "MOD-argos-inventory.md"}
    assert all(len(sha) == 64 for sha in manifest["files"].values())


def test_packs_are_reproducible(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    docs = docs_pack.load_docs(root)
    selected = docs_pack.select_docs(docs, phases=["03"], modules=[], include_internal=False)
    first = docs_pack.build_pack(selected, tmp_path / "a", "x", "2026-09-17", pdf=False)
    second = docs_pack.build_pack(selected, tmp_path / "b", "x", "2026-09-17", pdf=False)
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()


def test_pdf_rendering_produces_a_pdf_per_document(tmp_path: Path) -> None:
    pytest.importorskip("markdown_pdf")
    root = _repo(tmp_path)
    docs = docs_pack.select_docs(
        docs_pack.load_docs(root), phases=[], modules=["argos-common"], include_internal=False
    )
    pack = docs_pack.build_pack(docs, tmp_path / "out", "pdf", "2026-09-17", pdf=True)
    assert (pack / "MOD-argos-common.pdf").read_bytes().startswith(b"%PDF")
    assert (pack / "INDICE.pdf").read_bytes().startswith(b"%PDF")


def test_the_check_command_exit_code_follows_coverage(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert docs_pack.main(["--root", str(root), "--check"]) == 0
    (root / "docs" / "tecnica" / "modulos" / "argos-common.md").unlink()
    assert docs_pack.main(["--root", str(root), "--check"]) == 1
