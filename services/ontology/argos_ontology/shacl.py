"""SHACL shapes over the inventory: coherence findings of the knowledge itself (ARG-034).

Some obligations do not probe customer systems but the coherence of what ARGOS knows: every
treatment declares a legal basis, every system holding health data is in the record of processing
activities, every confirmed AI system has an AI Act risk class. The relevant slice of the AGE graph
is exported to an ephemeral RDF graph with a fixed mapping and validated in memory with pySHACL
(deviation note ARG-034-040).
"""

from dataclasses import dataclass
from pathlib import Path

from pyshacl import validate
from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.term import Node

from argos_inventory.graph.model import system_key
from argos_inventory.graph.store import GraphStore
from argos_ontology.vocabulary import LIBRARY_DIR

G = Namespace("urn:argos:graph:")
N = Namespace("urn:argos:node:")
SH = Namespace("http://www.w3.org/ns/shacl#")
SHAPES_DIR = LIBRARY_DIR / "ontology" / "shapes"

_TREATMENTS = "MATCH (t:Treatment) RETURN t.key, t.legal_basis, t.retention"
_DECLARED = "MATCH (s:System)-[:DECLARED_IN]->(t:Treatment) RETURN s.key, t.key"
_HEALTH_SYSTEMS = (
    "MATCH (t:Table)-[:CONTAINS]->(c:Column)-[:CLASSIFIED_AS]->(k:Category) "
    "WHERE k.name STARTS WITH 'special_category.health' AND coalesce(c.missing, false) = false "
    "RETURN DISTINCT t.system_id"
)
_CONFIRMED_AI = "MATCH (a:AISystem {status: 'confirmed'}) RETURN a.key, a.risk_class"


@dataclass(frozen=True, slots=True, order=True)
class ShapeFinding:
    node: str
    shape: str
    message: str
    severity: str


def _literal(value: object) -> Literal | None:
    text = "" if value is None else str(value).strip()
    return Literal(text) if text else None


def export_graph(store: GraphStore) -> Graph:
    """The fixed AGE-to-RDF mapping: node key -> urn:argos:node:<key>, label -> class, props."""
    data = Graph()
    with store.connection() as conn:
        for row in store.query(_TREATMENTS, columns=("key", "legal_basis", "retention"), conn=conn):
            node = N[str(row["key"])]
            data.add((node, RDF.type, G.Treatment))
            for prop in ("legal_basis", "retention"):
                value = _literal(row[prop])
                if value is not None:
                    data.add((node, G[prop], value))
        for row in store.query(_DECLARED, columns=("system", "treatment"), conn=conn):
            data.add((N[str(row["system"])], G.declared_in, N[str(row["treatment"])]))
        for row in store.query(_HEALTH_SYSTEMS, columns=("system_id",), conn=conn):
            data.add((N[system_key(str(row["system_id"]))], RDF.type, G.HealthDataSystem))
        for row in store.query(_CONFIRMED_AI, columns=("key", "risk_class"), conn=conn):
            node = N[str(row["key"])]
            data.add((node, RDF.type, G.ConfirmedAISystem))
            risk = _literal(row["risk_class"])
            if risk is not None:
                data.add((node, G.risk_class, risk))
    return data


def load_shapes(shapes_dir: Path = SHAPES_DIR) -> Graph:
    shapes = Graph()
    for path in sorted(shapes_dir.glob("*.ttl")):
        shapes.parse(path, format="turtle")
    return shapes


def _shape_name(shapes: Graph, report: Graph, result: Node) -> str:
    """The named NodeShape of a result, even when the failing constraint is a property shape."""
    source = report.value(result, SH.sourceShape)
    if source is None:
        return ""
    parent = next(iter(shapes.subjects(SH.property, source)), None)
    named = parent if isinstance(parent, URIRef) else source
    return str(named).removeprefix(str(G))


def validate_graph(data: Graph, shapes: Graph) -> list[ShapeFinding]:
    """One finding per validation result, sorted; an empty list means the data conforms."""
    _, report, _ = validate(data, shacl_graph=shapes, inference="none", advanced=False)
    if not isinstance(report, Graph):  # pragma: no cover - pyshacl returns a graph by default
        raise TypeError("pyshacl did not return a report graph")
    findings: set[ShapeFinding] = set()
    for result in report.subjects(RDF.type, SH.ValidationResult):
        focus = report.value(result, SH.focusNode)
        severity = report.value(result, SH.resultSeverity)
        message = report.value(result, SH.resultMessage)
        findings.add(
            ShapeFinding(
                node=str(focus).removeprefix(str(N)),
                shape=_shape_name(shapes, report, result),
                message=str(message or ""),
                severity=str(severity).rsplit("#", 1)[-1].lower(),
            )
        )
    return sorted(findings)


def run_shapes(store: GraphStore, shapes: Graph | None = None) -> list[ShapeFinding]:
    return validate_graph(export_graph(store), shapes if shapes is not None else load_shapes())
