"""Closed vocabulary of the normative ontology: namespaces, classes and properties (ARG-031).

The core file under library/ontology/core is content published with the bundle; this module is
the code-side mirror that tests keep aligned with it (deviation note ARG-031-033, ADR-0006).
"""

from pathlib import Path

from rdflib import Graph, Namespace

ARGOS = Namespace("https://ns.argos.eu/core#")
NORMS = Namespace("https://ns.argos.eu/norms/")
DPV = Namespace("https://w3id.org/dpv#")
ELI = Namespace("http://data.europa.eu/eli/ontology#")
ODRL = Namespace("http://www.w3.org/ns/odrl/2/")

LIBRARY_DIR = Path(__file__).resolve().parents[3] / "library"
CORE_FILE = LIBRARY_DIR / "ontology" / "core" / "argos-core.ttl"
ONTOLOGY_VERSION = "1.0.0"

CLASSES = (
    "Norm",
    "Article",
    "Obligation",
    "AssetClass",
    "Challenge",
    "Verification",
    "EvidenceType",
)
# name -> (domain, range); None where the core leaves it open
OBJECT_PROPERTIES: dict[str, tuple[str | None, str | None]] = {
    "derivesFrom": ("Obligation", "Article"),
    "partOf": ("Article", "Norm"),
    "supersedes": ("Obligation", "Obligation"),
    "equivalentTo": (None, None),
    "dataCategory": ("AssetClass", None),
    "appliesTo": ("Obligation", "AssetClass"),
    "verifiedBy": ("Obligation", "Challenge"),
    "evidenceType": ("Challenge", "EvidenceType"),
}
DATATYPE_PROPERTIES = (
    "eli",
    "inForceFrom",
    "inForceUntil",
    "severity",
    "verificationPending",
    "graphLabel",
    "selectorJson",
    "challengeId",
)
SEVERITIES = ("critical", "high", "medium", "low")
EVIDENCE_TYPES = ("query_result", "configuration", "log_extract", "document")
PREFIXES = {"argos": ARGOS, "n": NORMS, "dpv": DPV, "eli": ELI, "odrl": ODRL}


def bind_prefixes(graph: Graph) -> Graph:
    for prefix, namespace in PREFIXES.items():
        graph.bind(prefix, namespace, replace=True)
    return graph


def load_core(path: Path = CORE_FILE) -> Graph:
    return bind_prefixes(Graph().parse(path, format="turtle"))
