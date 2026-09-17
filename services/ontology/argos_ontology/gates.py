"""The five editorial gates of the ontology (Plan Director §8.2, deviation note ARG-034-040).

Nothing reaches a publication unless every gate passes:
1. syntax: templates compile, generated Turtle is current and every Turtle file parses;
2. consistency: domains and ranges hold, only the closed vocabulary is used, selectors are valid;
3. coverage: every obligation has a challenge or a pending reason and applies to an asset class;
4. traceability: every obligation cites its source article and the matrix has no orphans;
5. signature: the bundle builds deterministically, signs and verifies with a throw-away key.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from rdflib import RDF, Graph, URIRef
from rdflib.term import Node

from argos_ontology.applicability import asset_class_errors
from argos_ontology.bundle import (
    BundleRejectedError,
    build_bundle,
    bundle_graph,
    sign_bundle,
    verify_bundle,
)
from argos_ontology.editorial.compiler import compile_file
from argos_ontology.traceability import build_matrix, library_graph, load_challenge_catalog
from argos_ontology.vocabulary import (
    ARGOS,
    CLASSES,
    DATATYPE_PROPERTIES,
    EVIDENCE_TYPES,
    LIBRARY_DIR,
    OBJECT_PROPERTIES,
    SEVERITIES,
)

GATE_NAMES = ("syntax", "consistency", "coverage", "traceability", "signature")
EDITORIAL_DIR = Path("ontology") / "editorial"
GENERATED_DIR = Path("ontology") / "norms" / "generated"
TEMPLATE_NAME = "obligation-template.yaml"
DRY_RUN_VERSION = "0.0.0"
DRY_RUN_DATE = date(2000, 1, 1)
_KNOWN_TERMS = {*CLASSES, *OBJECT_PROPERTIES, *DATATYPE_PROPERTIES, *EVIDENCE_TYPES, ""}
_COVERAGE_MARKERS = (
    "without challenge or verificationPending",
    "a verificationPending reason at once",
)


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    ok: bool
    errors: tuple[str, ...]


def _result(name: str, errors: list[str]) -> GateResult:
    return GateResult(name, not errors, tuple(errors))


def gate_syntax(library_dir: Path) -> GateResult:
    errors: list[str] = []
    editorial = library_dir / EDITORIAL_DIR
    generated = library_dir / GENERATED_DIR
    expected: set[str] = set()
    for template in sorted(editorial.glob("*.yaml")):
        if template.name == TEMPLATE_NAME:
            continue
        target = generated / f"{template.stem}.ttl"
        expected.add(target.name)
        try:
            turtle = compile_file(template)
        except ValueError as exc:
            errors.append(f"{template.name}: {exc}")
            continue
        if not target.is_file() or target.read_bytes() != turtle:
            errors.append(f"{target.name}: generated Turtle is missing or stale")
    for leftover in sorted(generated.glob("*.ttl")):
        if leftover.name not in expected:
            errors.append(f"{leftover.name}: generated Turtle without editorial template")
    for turtle_file in sorted(library_dir.glob("ontology/**/*.ttl")):
        try:
            Graph().parse(turtle_file, format="turtle")
        except Exception as exc:  # noqa: BLE001 - rdflib raises many parser exception types
            errors.append(f"{turtle_file.relative_to(library_dir).as_posix()}: {exc}")
    return _result("syntax", errors)


def _typed(graph: Graph, node: Node, class_name: str) -> bool:
    return (node, RDF.type, ARGOS[class_name]) in graph


def gate_consistency(graph: Graph) -> GateResult:
    errors: list[str] = []
    for subject, predicate, obj in graph:
        for term in (subject, predicate, obj):
            if isinstance(term, URIRef) and str(term).startswith(str(ARGOS)):
                local = str(term).removeprefix(str(ARGOS))
                if local not in _KNOWN_TERMS:
                    errors.append(f"unknown vocabulary term: argos:{local}")
    for name, (domain, range_) in OBJECT_PROPERTIES.items():
        for subject, obj in graph.subject_objects(ARGOS[name]):
            if domain is not None and not _typed(graph, subject, domain):
                errors.append(f"{subject}: argos:{name} needs a subject of type argos:{domain}")
            if range_ is not None and not _typed(graph, obj, range_):
                errors.append(f"{subject}: argos:{name} points to {obj}, not an argos:{range_}")
    for obligation, severity in graph.subject_objects(ARGOS.severity):
        if str(severity) not in SEVERITIES:
            errors.append(f"{obligation}: invalid severity {severity!s}")
    errors.extend(asset_class_errors(graph))
    return _result("consistency", sorted(set(errors)))


def gate_coverage(graph: Graph, library_dir: Path) -> GateResult:
    catalog = load_challenge_catalog(library_dir / "challenges" / "catalog.yaml")
    _, matrix_errors = build_matrix(graph, catalog)
    errors = [e for e in matrix_errors if any(marker in e for marker in _COVERAGE_MARKERS)]
    for obligation in sorted(graph.subjects(RDF.type, ARGOS.Obligation), key=str):
        if graph.value(obligation, ARGOS.appliesTo) is None:
            errors.append(f"{obligation}: obligation applies to no asset class")
    return _result("coverage", errors)


def gate_traceability(graph: Graph, library_dir: Path) -> GateResult:
    catalog = load_challenge_catalog(library_dir / "challenges" / "catalog.yaml")
    _, matrix_errors = build_matrix(graph, catalog)
    errors = [e for e in matrix_errors if not any(marker in e for marker in _COVERAGE_MARKERS)]
    for obligation in sorted(graph.subjects(RDF.type, ARGOS.Obligation), key=str):
        article = graph.value(obligation, ARGOS.derivesFrom)
        if article is None:
            errors.append(f"{obligation}: obligation cites no source article")
        elif graph.value(article, ARGOS.partOf) is None:
            errors.append(f"{obligation}: article {article} is not part of any declared norm")
    return _result("traceability", errors)


def gate_signature(library_dir: Path) -> GateResult:
    key = Ed25519PrivateKey.generate()
    public_key = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    try:
        first, manifest = build_bundle(library_dir, DRY_RUN_VERSION, DRY_RUN_DATE)
        second, _ = build_bundle(library_dir, DRY_RUN_VERSION, DRY_RUN_DATE)
    except ValueError as exc:
        return _result("signature", [str(exc)])
    if first != second:
        return _result("signature", ["bundle build is not deterministic"])
    signer = _KeySigner(key, public_key)
    try:
        verified = verify_bundle(first, sign_bundle(manifest, signer), public_key)
        bundle_graph(verified)
    except BundleRejectedError as exc:
        return _result("signature", [f"bundle does not verify: {exc}"])
    return _result("signature", [])


class _KeySigner:
    def __init__(self, key: Ed25519PrivateKey, public_key: bytes) -> None:
        self._key = key
        self._public_key = public_key

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def public_key(self) -> bytes:
        return self._public_key


def run_gates(library_dir: Path = LIBRARY_DIR) -> list[GateResult]:
    """All five gates in order; the graph-based ones only run when the Turtle parses."""
    syntax = gate_syntax(library_dir)
    if not syntax.ok:
        skipped = ("skipped: syntax gate failed",)
        return [syntax, *(GateResult(name, False, skipped) for name in GATE_NAMES[1:])]
    graph = library_graph(library_dir)
    checks: list[Callable[[], GateResult]] = [
        lambda: gate_consistency(graph),
        lambda: gate_coverage(graph, library_dir),
        lambda: gate_traceability(graph, library_dir),
        lambda: gate_signature(library_dir),
    ]
    return [syntax, *(check() for check in checks)]
