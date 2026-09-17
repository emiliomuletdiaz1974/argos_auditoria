"""ARG-034 · coherence shapes turn inventory gaps into findings (pure, on an RDF data graph)."""

from rdflib import RDF, Graph, Literal

from argos_ontology.shacl import G, N, ShapeFinding, load_shapes, validate_graph

SHAPES = load_shapes()


def _treatment(data: Graph, key: str, legal_basis: str | None, retention: str | None) -> None:
    data.add((N[key], RDF.type, G.Treatment))
    if legal_basis is not None:
        data.add((N[key], G.legal_basis, Literal(legal_basis)))
    if retention is not None:
        data.add((N[key], G.retention, Literal(retention)))


def _ai_system(
    data: Graph,
    key: str,
    risk_class: str | None,
    documentation_ref: str | None,
    oversight_owner: str | None,
) -> None:
    data.add((N[key], RDF.type, G.ConfirmedAISystem))
    for name, value in (
        ("risk_class", risk_class),
        ("documentation_ref", documentation_ref),
        ("oversight_owner", oversight_owner),
    ):
        if value is not None:
            data.add((N[key], G[name], Literal(value)))


def test_a_coherent_inventory_has_no_findings() -> None:
    data = Graph()
    _treatment(data, "t1", "GDPR 9.2.h", "15 years")
    data.add((N["s1"], RDF.type, G.HealthDataSystem))
    data.add((N["s1"], G.declared_in, N["t1"]))
    _ai_system(data, "a1", "high", "DOC-IA-001", "dpo@example.invalid")
    assert validate_graph(data, SHAPES) == []


def test_each_gap_is_one_finding_with_its_shape_message_and_severity() -> None:
    data = Graph()
    _treatment(data, "t1", None, None)
    data.add((N["s1"], RDF.type, G.HealthDataSystem))
    _ai_system(data, "a1", None, None, None)
    _ai_system(data, "a2", "very-high", "DOC-IA-002", "dpo@example.invalid")
    findings = validate_graph(data, SHAPES)
    assert findings == sorted(findings)
    assert {(f.node, f.shape, f.severity) for f in findings} == {
        ("a1", "ConfirmedAISystemShape", "violation"),
        ("a1", "AISystemDocumentationShape", "violation"),
        ("a1", "AIHumanOversightShape", "violation"),
        ("a2", "ConfirmedAISystemShape", "violation"),
        ("s1", "HealthDataSystemShape", "violation"),
        ("t1", "TreatmentShape", "violation"),
        ("t1", "TreatmentShape", "warning"),
    }
    messages = {f.message for f in findings if f.node == "t1"}
    assert messages == {
        "Tratamiento sin base jurídica declarada",
        "Tratamiento sin plazo de conservación",
    }


def test_findings_are_value_objects() -> None:
    finding = ShapeFinding("t1", "TreatmentShape", "m", "warning")
    assert finding == ShapeFinding("t1", "TreatmentShape", "m", "warning")
    earlier = ShapeFinding("a1", "ConfirmedAISystemShape", "m", "violation")
    assert sorted([finding, earlier]) == [earlier, finding]


def test_shapes_live_in_the_ontology_library_and_parse() -> None:
    assert len(SHAPES) > 0
