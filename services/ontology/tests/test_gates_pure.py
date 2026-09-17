"""ARG-038 · each editorial gate passes a sound library and rejects a planted error."""

import importlib.util
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from argos_ontology.editorial.compiler import compile_file
from argos_ontology.gates import (
    GATE_NAMES,
    gate_consistency,
    gate_coverage,
    gate_signature,
    gate_syntax,
    gate_traceability,
    run_gates,
)
from argos_ontology.traceability import library_graph
from argos_ontology.vocabulary import LIBRARY_DIR

ROOT = Path(__file__).resolve().parents[3]
NORM = """\
@prefix argos: <https://ns.argos.eu/core#> .
@prefix n: <https://ns.argos.eu/norms/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

n:RGPD a argos:Norm ;
  rdfs:label "Reglamento General de Protección de Datos"@es ;
  argos:eli "http://data.europa.eu/eli/reg/2016/679/oj"^^xsd:anyURI ;
  argos:inForceFrom "2018-05-25"^^xsd:date .
n:RGPD-32 a argos:Article ; argos:partOf n:RGPD ;
  rdfs:label "Artículo 32. Seguridad del tratamiento"@es .
"""
TEMPLATE = """\
id: OBL-RGPD-32-1
norma: RGPD
articulo: "32"
titulo: Cifrado de categorías especiales
vigente_desde: 2018-05-25
severidad: critical
aplica_a: [AC-stored-health-data]
verificado_por: [sec-encryption-at-rest]
"""
CATALOG = """\
challenges:
  - id: sec-encryption-at-rest
    family: security
    evidence_type: configuration
    description: Cifrado en reposo verificado
"""


def _write_template(library: Path, text: str) -> None:
    template = library / "ontology" / "editorial" / "OBL-RGPD-32-1.yaml"
    template.write_text(text, encoding="utf-8")
    generated = library / "ontology" / "norms" / "generated" / "OBL-RGPD-32-1.ttl"
    generated.write_bytes(compile_file(template))


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    for part in ("core", "asset-classes"):
        shutil.copytree(LIBRARY_DIR / "ontology" / part, root / "ontology" / part)
    (root / "ontology" / "editorial").mkdir(parents=True)
    (root / "ontology" / "norms" / "generated").mkdir(parents=True)
    (root / "ontology" / "norms" / "RGPD.ttl").write_text(NORM, encoding="utf-8")
    (root / "challenges").mkdir()
    (root / "challenges" / "catalog.yaml").write_text(CATALOG, encoding="utf-8")
    _write_template(root, TEMPLATE)
    return root


def _failing(results: list[Any]) -> dict[str, tuple[str, ...]]:
    return {r.name: r.errors for r in results if not r.ok}


def test_a_sound_library_passes_the_five_gates(library: Path) -> None:
    results = run_gates(library)
    assert [r.name for r in results] == list(GATE_NAMES)
    assert _failing(results) == {}


def test_the_shipped_library_passes_the_five_gates() -> None:
    assert _failing(run_gates(LIBRARY_DIR)) == {}


def test_syntax_rejects_stale_generated_turtle(library: Path) -> None:
    template = library / "ontology" / "editorial" / "OBL-RGPD-32-1.yaml"
    template.write_text(TEMPLATE.replace("critical", "low"), encoding="utf-8")
    [error] = gate_syntax(library).errors
    assert "missing or stale" in error


def test_syntax_rejects_unparseable_turtle_and_skips_the_other_gates(library: Path) -> None:
    (library / "ontology" / "norms" / "broken.ttl").write_text("n:x a .", encoding="utf-8")
    results = run_gates(library)
    assert "broken.ttl" in results[0].errors[0]
    assert all(r.errors == ("skipped: syntax gate failed",) for r in results[1:])


def test_syntax_rejects_generated_turtle_without_template(library: Path) -> None:
    (library / "ontology" / "editorial" / "OBL-RGPD-32-1.yaml").unlink()
    assert "without editorial template" in gate_syntax(library).errors[0]


def _graph_gate(gate: Callable[..., Any], library: Path, needs_library: bool) -> tuple[str, ...]:
    graph = library_graph(library)
    result = gate(graph, library) if needs_library else gate(graph)
    return tuple(result.errors)


def test_consistency_rejects_an_undeclared_asset_class(library: Path) -> None:
    _write_template(library, TEMPLATE.replace("AC-stored-health-data", "AC-unknown-class"))
    errors = _graph_gate(gate_consistency, library, needs_library=False)
    assert any("argos:appliesTo points to" in e and "AC-unknown-class" in e for e in errors)


def test_consistency_rejects_terms_outside_the_vocabulary(library: Path) -> None:
    extra = "@prefix argos: <https://ns.argos.eu/core#> .\nargos:Obligation argos:weight 3 .\n"
    (library / "ontology" / "norms" / "extra.ttl").write_text(extra, encoding="utf-8")
    errors = _graph_gate(gate_consistency, library, needs_library=False)
    assert "unknown vocabulary term: argos:weight" in errors


def test_consistency_rejects_an_invalid_asset_class_selector(library: Path) -> None:
    bad = (
        "@prefix argos: <https://ns.argos.eu/core#> .\n@prefix n: <https://ns.argos.eu/norms/> .\n"
        'n:AC-bad a argos:AssetClass ; argos:graphLabel "Column" ;\n'
        '  argos:selectorJson """{"label": "Column", "category": null}""" .\n'
    )
    (library / "ontology" / "asset-classes" / "bad.ttl").write_text(bad, encoding="utf-8")
    errors = _graph_gate(gate_consistency, library, needs_library=False)
    assert any("AC-bad: invalid selector" in e for e in errors)


def test_coverage_rejects_an_obligation_without_challenge(library: Path) -> None:
    _write_template(library, TEMPLATE.replace("verificado_por: [sec-encryption-at-rest]\n", ""))
    (library / "challenges" / "catalog.yaml").write_text("challenges: []\n", encoding="utf-8")
    errors = _graph_gate(gate_coverage, library, needs_library=True)
    assert any("without challenge or verificationPending" in e for e in errors)


def test_coverage_rejects_an_obligation_without_asset_class(library: Path) -> None:
    _write_template(library, TEMPLATE.replace("aplica_a: [AC-stored-health-data]\n", ""))
    errors = _graph_gate(gate_coverage, library, needs_library=True)
    assert any("applies to no asset class" in e for e in errors)


def test_traceability_rejects_an_article_outside_any_norm(library: Path) -> None:
    (library / "ontology" / "norms" / "RGPD.ttl").unlink()
    errors = _graph_gate(gate_traceability, library, needs_library=True)
    assert any("is not part of any declared norm" in e for e in errors)


def test_traceability_rejects_orphan_catalog_challenges(library: Path) -> None:
    catalog = CATALOG + (
        "  - id: ret-table-retention\n    family: retention\n"
        "    evidence_type: query_result\n    description: Plazo en tablas\n"
    )
    (library / "challenges" / "catalog.yaml").write_text(catalog, encoding="utf-8")
    errors = _graph_gate(gate_traceability, library, needs_library=True)
    assert "orphan challenge without obligation: ret-table-retention" in errors


def test_signature_rejects_a_library_that_cannot_be_bundled(tmp_path: Path) -> None:
    result = gate_signature(tmp_path)
    assert not result.ok
    assert "no ontology content" in result.errors[0]


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ontology_gates", ROOT / "tools" / "ontology_gates.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_tool_exit_code_follows_the_gates(library: Path) -> None:
    tool = _tool()
    assert tool.main(["--library", str(library)]) == 0
    (library / "ontology" / "norms" / "RGPD.ttl").unlink()
    assert tool.main(["--library", str(library)]) == 1
