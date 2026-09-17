"""ARG-038 · editorial templates compile to canonical, injection-proof Turtle."""

import importlib.util
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from rdflib import RDF, RDFS, XSD, Graph, Literal

from argos_ontology.editorial.compiler import (
    compile_obligation,
    obligation_graph,
    parse_obligation,
)
from argos_ontology.vocabulary import ARGOS, LIBRARY_DIR, NORMS

TEMPLATE = """\
id: OBL-RGPD-32-1
norma: RGPD
articulo: "32"
titulo: Seguridad del tratamiento — cifrado de categorías especiales
vigente_desde: 2018-05-25
severidad: critical
texto_resumen: >
  Los datos de categoría especial almacenados deben contar con cifrado
  en reposo verificado.
aplica_a: [AC-stored-health-data]
verificado_por: [sec-encryption-at-rest, sec-backup-encryption]
equivalencias: [ENS:op.exp.10]
"""
REORDERED = """\
verificado_por: [sec-backup-encryption, sec-encryption-at-rest]
equivalencias: [ENS:op.exp.10]
severidad: critical
aplica_a: [AC-stored-health-data]
texto_resumen: >
  Los datos de categoría especial almacenados
  deben contar con cifrado en reposo verificado.
titulo: Seguridad del tratamiento — cifrado de categorías especiales
articulo: "32"
norma: RGPD
vigente_desde: "2018-05-25"
id: OBL-RGPD-32-1
"""
ROOT = Path(__file__).resolve().parents[3]


def _valid(**changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "id": "OBL-RGPD-32-1",
        "norm": "RGPD",
        "article": "32",
        "title": "Seguridad",
        "in_force_from": date(2018, 5, 25),
        "severity": "critical",
        "applies_to": ["AC-stored-health-data"],
        "verified_by": ["sec-encryption-at-rest"],
    }
    document.update(changes)
    return {k: v for k, v in document.items() if v is not None}


def test_the_same_template_always_yields_the_same_bytes() -> None:
    first = compile_obligation(TEMPLATE)
    assert first == compile_obligation(TEMPLATE)
    assert first == compile_obligation(REORDERED)


def test_the_obligation_graph_carries_the_three_planes() -> None:
    graph = Graph().parse(data=compile_obligation(TEMPLATE), format="turtle")
    node = NORMS["OBL-RGPD-32-1"]
    assert (node, RDF.type, ARGOS.Obligation) in graph
    assert (node, ARGOS.derivesFrom, NORMS["RGPD-32"]) in graph
    assert (node, ARGOS.severity, Literal("critical")) in graph
    assert (node, ARGOS.inForceFrom, Literal(date(2018, 5, 25), datatype=XSD.date)) in graph
    assert (node, ARGOS.appliesTo, NORMS["AC-stored-health-data"]) in graph
    assert (node, ARGOS.equivalentTo, NORMS["ENS-op-exp-10"]) in graph
    for challenge in ("sec-encryption-at-rest", "sec-backup-encryption"):
        challenge_node = NORMS[f"CH-{challenge}"]
        assert (node, ARGOS.verifiedBy, challenge_node) in graph
        assert (challenge_node, ARGOS.challengeId, Literal(challenge)) in graph
    comment = graph.value(node, RDFS.comment)
    assert isinstance(comment, Literal) and "\n" not in str(comment)


def test_dotted_articles_become_node_names() -> None:
    graph = obligation_graph(parse_obligation(_valid(id="OBL-RGPD-5-1-E", article="5.1.e")))
    assert (NORMS["OBL-RGPD-5-1-E"], ARGOS.derivesFrom, NORMS["RGPD-5-1-e"]) in graph


def test_titles_cannot_break_or_inject_turtle() -> None:
    hostile = 'Title "quoted" ;\n  argos:severity "low" . <urn:x> a argos:Obligation {} #'
    turtle = obligation_graph(parse_obligation(_valid(title=hostile))).serialize(format="turtle")
    graph = Graph().parse(data=turtle, format="turtle")
    node = NORMS["OBL-RGPD-32-1"]
    assert graph.value(node, RDFS.label) == Literal(hostile, lang="es")
    assert set(graph.objects(node, ARGOS.severity)) == {Literal("critical")}
    assert len(set(graph.subjects(RDF.type, ARGOS.Obligation))) == 1


def test_a_pending_verification_is_recorded() -> None:
    spec = parse_obligation(_valid(verified_by=None, verification_pending="no probe yet"))
    graph = obligation_graph(spec)
    assert graph.value(NORMS["OBL-RGPD-32-1"], ARGOS.verificationPending) == Literal("no probe yet")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"severity": "alta"}, "invalid severity"),
        ({"id": "OBL-rgpd-32"}, "invalid obligation id"),
        ({"id": "RGPD-32"}, "invalid obligation id"),
        ({"norm": "rgpd"}, "invalid norm id"),
        ({"article": "art. 32"}, "invalid article"),
        ({"in_force_from": "25/05/2018"}, "invalid in_force_from"),
        ({"applies_to": ["AC-Datos-Salud"]}, "invalid identifiers in applies_to"),
        ({"applies_to": "AC-stored-health-data"}, "must be a list"),
        ({"verified_by": ["SEC_1"]}, "invalid identifiers in verified_by"),
        ({"verified_by": ["sec-a", "sec-a"]}, "repeated identifiers"),
        ({"equivalences": ["ENS op.exp.10"]}, "invalid identifiers in equivalences"),
        ({"title": "   "}, "non-empty text"),
        ({"verification_pending": ""}, "verification_pending"),
    ],
)
def test_invalid_templates_are_rejected(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_obligation(_valid(**changes))


def test_missing_fields_are_reported() -> None:
    document = _valid()
    del document["severity"]
    with pytest.raises(ValueError, match="missing fields: \\['severity'\\]"):
        parse_obligation(document)


def test_the_shipped_template_compiles() -> None:
    template = LIBRARY_DIR / "ontology" / "editorial" / "obligation-template.yaml"
    assert b"OBL-RGPD-32-1" in compile_obligation(template.read_text(encoding="utf-8"))


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ontology_compile", ROOT / "tools" / "ontology_compile.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_tool_writes_and_then_checks_generated_turtle(tmp_path: Path) -> None:
    source, output = tmp_path / "editorial", tmp_path / "generated"
    source.mkdir()
    (source / "OBL-RGPD-32-1.yaml").write_text(TEMPLATE, encoding="utf-8")
    (source / "obligation-template.yaml").write_text("id: ignored\n", encoding="utf-8")
    tool = _tool()
    assert tool.main(["--check", str(source), str(output)]) == 1
    assert tool.main([str(source), str(output)]) == 0
    assert [p.name for p in output.iterdir()] == ["OBL-RGPD-32-1.ttl"]
    assert tool.main(["--check", str(source), str(output)]) == 0
    (output / "OBL-RGPD-32-1.ttl").write_bytes(b"# edited by hand\n")
    assert tool.main(["--check", str(source), str(output)]) == 1
