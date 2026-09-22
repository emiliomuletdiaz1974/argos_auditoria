"""Technical documentation: coverage check and client documentation packs.

Usage:
  uv run python tools/docs_pack.py --check
  uv run python tools/docs_pack.py --phase 03 --label hospital-x [--module NAME] [--all]
                                   [--include-internal] [--no-pdf] [--output DIR]

Every uv workspace member needs docs/tecnica/modulos/<name>.md and every closed phase (one that
published docs/fases/interfaces-FNN.md) needs docs/tecnica/fases/FNN-*.md, both listed in
docs/tecnica/README.md. A pack copies the selected documents (client ones only, unless asked),
renders them to PDF and writes an index and a manifest with the SHA-256 of every file.
"""

import argparse
import hashlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
TECH_DIR = Path("docs") / "tecnica"
PHASE_INTERFACES = re.compile(r"^interfaces-F(\d{2})\.md$")
REQUIRED_FIELDS = ("id", "kind", "title", "version", "commit", "date", "status", "confidentiality")
KIND_FIELDS = {"module": ("module", "phases"), "phase": ("phase",)}
KIND_DIRS = {"module": "modulos", "phase": "fases"}
STATUSES = ("draft", "current", "superseded")
CONFIDENTIALITY = ("client", "internal")
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True, slots=True)
class TechnicalDoc:
    path: Path
    meta: dict[str, Any]
    body: str


def parse_doc(path: Path) -> TechnicalDoc:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = FRONT_MATTER.match(text)
    if match is None:
        raise ValueError(f"{path.name}: no front matter block")
    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict):
        raise ValueError(f"{path.name}: front matter must be a mapping")
    meta = {key: str(value) if key == "date" else value for key, value in meta.items()}
    kind = meta.get("kind")
    if kind not in KIND_FIELDS:
        raise ValueError(f"{path.name}: unknown kind {kind!r}")
    missing = [f for f in (*REQUIRED_FIELDS, *KIND_FIELDS[kind]) if meta.get(f) in (None, "")]
    if missing:
        raise ValueError(f"{path.name}: missing fields {missing}")
    if meta["confidentiality"] not in CONFIDENTIALITY:
        raise ValueError(f"{path.name}: confidentiality must be one of {CONFIDENTIALITY}")
    if meta["status"] not in STATUSES:
        raise ValueError(f"{path.name}: status must be one of {STATUSES}")
    if kind == "module":
        meta["phases"] = [str(p) for p in meta["phases"]]
    else:
        meta["phase"] = str(meta["phase"])
    return TechnicalDoc(path, meta, text[match.end() :].lstrip("\n"))


def load_docs(root: Path = ROOT) -> list[TechnicalDoc]:
    tech = root / TECH_DIR
    paths = sorted((tech / "modulos").glob("*.md")) + sorted((tech / "fases").glob("*.md"))
    return [parse_doc(path) for path in paths]


NPM_MODULES = ("console",)


def workspace_modules(root: Path = ROOT) -> list[str]:
    """The modules of the product: every uv workspace member and the console (npm, ADR-0013)."""
    workspace = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    names = []
    for member in workspace["tool"]["uv"]["workspace"]["members"]:
        project = tomllib.loads((root / member / "pyproject.toml").read_text(encoding="utf-8"))
        names.append(str(project["project"]["name"]))
    for folder in NPM_MODULES:
        package = root / folder / "package.json"
        if package.is_file():
            names.append(str(json.loads(package.read_text(encoding="utf-8"))["name"]))
    return sorted(names)


def closed_phases(root: Path = ROOT) -> list[str]:
    found = (PHASE_INTERFACES.match(p.name) for p in (root / "docs" / "fases").glob("*.md"))
    return sorted(m.group(1) for m in found if m)


def coverage_errors(root: Path = ROOT) -> list[str]:
    """Everything that stops the technical documentation from matching the repository."""
    errors: list[str] = []
    try:
        docs = load_docs(root)
    except ValueError as exc:
        return [str(exc)]
    ids = [d.meta["id"] for d in docs]
    errors += [f"repeated document id: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for doc in docs:
        if doc.path.parent.name != KIND_DIRS[doc.meta["kind"]]:
            errors.append(f"{doc.path.name}: a {doc.meta['kind']} document outside its folder")
    documented = {d.meta["module"] for d in docs if d.meta["kind"] == "module"}
    modules = workspace_modules(root)
    errors += [f"module {m} has no module document" for m in modules if m not in documented]
    errors += [f"module document for unknown module {m}" for m in sorted(documented - set(modules))]
    closed = {d.meta["phase"] for d in docs if d.meta["kind"] == "phase"}
    errors += [
        f"phase {p} is closed but has no closure document"
        for p in closed_phases(root)
        if p not in closed
    ]
    index = root / TECH_DIR / "README.md"
    listed = index.read_text(encoding="utf-8") if index.is_file() else ""
    for doc in docs:
        link = f"{doc.path.parent.name}/{doc.path.name}"
        if f"({link})" not in listed:
            errors.append(f"{link} is not linked from docs/tecnica/README.md")
    return errors


def select_docs(
    docs: list[TechnicalDoc], phases: list[str], modules: list[str], include_internal: bool
) -> list[TechnicalDoc]:
    """Closure documents of the phases, modules of those phases and the named modules."""
    chosen = []
    for doc in docs:
        if doc.meta["confidentiality"] == "internal" and not include_internal:
            continue
        if doc.meta["kind"] == "phase":
            wanted = doc.meta["phase"] in phases
        else:
            wanted = doc.meta["module"] in modules or bool(set(doc.meta["phases"]) & set(phases))
        if wanted:
            chosen.append(doc)
    return sorted(chosen, key=lambda d: (d.meta["kind"] != "phase", d.meta["id"]))


def _render(doc: TechnicalDoc) -> str:
    rows = [
        ("Documento", doc.meta["id"]),
        ("Versión", doc.meta["version"]),
        ("Commit", doc.meta["commit"]),
        ("Fecha", doc.meta["date"]),
        ("Estado", doc.meta["status"]),
        ("Confidencialidad", doc.meta["confidentiality"]),
    ]
    table = "| Campo | Valor |\n|---|---|\n" + "".join(f"| {k} | {v} |\n" for k, v in rows)
    return f"{table}\n{doc.body}"


def _index(docs: list[TechnicalDoc], label: str, date: str) -> str:
    lines = [
        f"# Documentación técnica de ARGOS · {label}",
        "",
        f"Paquete generado el {date}.",
        "",
        "| Documento | Título | Versión | Commit | Fecha |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {d.meta['id']} | {d.meta['title']} | {d.meta['version']} | {d.meta['commit']} "
        f"| {d.meta['date']} |"
        for d in docs
    ]
    return "\n".join(lines) + "\n"


def _pdf(markdown: str, title: str, target: Path) -> None:
    from markdown_pdf import MarkdownPdf, Section

    document = MarkdownPdf(toc_level=2)
    document.add_section(Section(markdown))
    document.meta["title"] = title
    document.save(str(target))


def build_pack(
    docs: list[TechnicalDoc], output: Path, label: str, date: str, pdf: bool = True
) -> Path:
    """Write the pack folder <date>-<label> and return it."""
    if not re.fullmatch(r"[a-z0-9-]+", label):
        raise ValueError("label must be lowercase letters, digits and hyphens")
    pack = output / f"{date}-{label}"
    pack.mkdir(parents=True, exist_ok=True)
    contents = {f"{d.meta['id']}.md": (_render(d), d.meta["title"]) for d in docs}
    contents["INDICE.md"] = (_index(docs, label, date), f"Documentación técnica · {label}")
    hashes: dict[str, str] = {}
    for name, (markdown, title) in sorted(contents.items()):
        (pack / name).write_text(markdown, encoding="utf-8", newline="\n")
        hashes[name] = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        if pdf:
            _pdf(markdown, title, pack / name.replace(".md", ".pdf"))
    manifest = {"label": label, "date": date, "files": hashes}
    (pack / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Technical documentation check and packs.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="fail on documentation gaps")
    parser.add_argument("--phase", action="append", default=[], help="two digits, e.g. 03")
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--include-internal", action="store_true")
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--label", default="documentacion")
    parser.add_argument("--output", type=Path, default=Path("dist") / "documentacion")
    args = parser.parse_args(argv)
    if args.check:
        errors = coverage_errors(args.root)
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"{len(errors)} documentation gap(s)")
        return 1 if errors else 0
    docs = load_docs(args.root)
    if args.all:
        args.phase = sorted({d.meta["phase"] for d in docs if d.meta["kind"] == "phase"})
        args.module = sorted({d.meta["module"] for d in docs if d.meta["kind"] == "module"})
    selected = select_docs(docs, args.phase, args.module, args.include_internal)
    if not selected:
        print("no documents match the selection", file=sys.stderr)
        return 1
    date = datetime.now(UTC).date().isoformat()
    pack = build_pack(selected, args.output, args.label, date, pdf=not args.no_pdf)
    print(f"{len(selected)} document(s) in {pack}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
