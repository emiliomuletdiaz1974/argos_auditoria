"""Deterministic compiler from editorial templates to canonical Turtle (ARG-038, ADR-0006).

The Turtle is built with rdflib, so titles with quotes or line breaks cannot break the syntax, and
the same template always yields the same bytes: diffs between releases stay readable.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from rdflib import RDF, RDFS, XSD, Graph, Literal, URIRef

from argos_ontology.editorial.translation import read_editorial, to_internal
from argos_ontology.vocabulary import ARGOS, NORMS, SEVERITIES, bind_prefixes

REQUIRED_FIELDS = ("id", "norm", "article", "title", "in_force_from", "severity")
OBLIGATION_ID = re.compile(r"^OBL-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
NORM_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
ARTICLE_ID = re.compile(r"^[0-9]+(?:\.[0-9a-z]+)*$")
ASSET_CLASS_ID = re.compile(r"^AC-[a-z0-9]+(?:-[a-z0-9]+)*$")
CHALLENGE_ID = re.compile(r"^[a-z]+-[a-z0-9]+(?:-[a-z0-9]+)*$")
EQUIVALENCE = re.compile(r"^([A-Z][A-Z0-9]*):([A-Za-z0-9.]+)$")


@dataclass(frozen=True, slots=True)
class ObligationSpec:
    id: str
    norm: str
    article: str
    title: str
    in_force_from: date
    severity: str
    summary: str | None
    applies_to: tuple[str, ...]
    verified_by: tuple[str, ...]
    equivalences: tuple[str, ...]
    verification_pending: str | None


def _text(document: Mapping[str, Any], field: str) -> str:
    value = document[field]
    if isinstance(value, bool) or not isinstance(value, str | int) or not str(value).strip():
        raise ValueError(f"field {field} must be a non-empty text")
    return str(value).strip()


def _ids(document: Mapping[str, Any], field: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    values = document.get(field) or []
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValueError(f"field {field} must be a list of identifiers")
    bad = [v for v in values if not pattern.match(v)]
    if bad:
        raise ValueError(f"invalid identifiers in {field}: {bad}")
    if len(set(values)) != len(values):
        raise ValueError(f"repeated identifiers in {field}")
    return tuple(sorted(values))


def parse_obligation(document: Mapping[str, Any]) -> ObligationSpec:
    missing = [f for f in REQUIRED_FIELDS if f not in document]
    if missing:
        raise ValueError(f"missing fields: {missing}")
    identifier = _text(document, "id")
    if not OBLIGATION_ID.match(identifier):
        raise ValueError(f"invalid obligation id: {identifier!r}")
    norm = _text(document, "norm")
    if not NORM_ID.match(norm):
        raise ValueError(f"invalid norm id: {norm!r}")
    article = _text(document, "article")
    if not ARTICLE_ID.match(article):
        raise ValueError(f"invalid article: {article!r}")
    severity = _text(document, "severity")
    if severity not in SEVERITIES:
        raise ValueError(f"invalid severity: {severity!r}")
    raw_date = document["in_force_from"]
    try:
        in_force = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date))
    except ValueError:
        raise ValueError(f"invalid in_force_from date: {raw_date!r}") from None
    pending = document.get("verification_pending")
    if pending is not None and (not isinstance(pending, str) or not pending.strip()):
        raise ValueError("verification_pending must be a non-empty text")
    summary = document.get("summary")
    return ObligationSpec(
        id=identifier,
        norm=norm,
        article=article,
        title=_text(document, "title"),
        in_force_from=in_force,
        severity=severity,
        summary=" ".join(str(summary).split()) if summary else None,
        applies_to=_ids(document, "applies_to", ASSET_CLASS_ID),
        verified_by=_ids(document, "verified_by", CHALLENGE_ID),
        equivalences=_ids(document, "equivalences", EQUIVALENCE),
        verification_pending=pending.strip() if pending else None,
    )


def article_node(norm: str, article: str) -> URIRef:
    return NORMS[f"{norm}-{article.replace('.', '-')}"]


def equivalence_node(equivalence: str) -> URIRef:
    match = EQUIVALENCE.match(equivalence)
    if match is None:
        raise ValueError(f"invalid equivalence: {equivalence!r}")
    framework, code = match.groups()
    return NORMS[f"{framework}-{code.replace('.', '-')}"]


def obligation_graph(spec: ObligationSpec) -> Graph:
    graph = bind_prefixes(Graph())
    node = NORMS[spec.id]
    graph.add((node, RDF.type, ARGOS.Obligation))
    graph.add((node, RDFS.label, Literal(spec.title, lang="es")))
    graph.add((node, ARGOS.derivesFrom, article_node(spec.norm, spec.article)))
    graph.add((node, ARGOS.severity, Literal(spec.severity)))
    graph.add((node, ARGOS.inForceFrom, Literal(spec.in_force_from, datatype=XSD.date)))
    if spec.summary:
        graph.add((node, RDFS.comment, Literal(spec.summary, lang="es")))
    for asset_class in spec.applies_to:
        graph.add((node, ARGOS.appliesTo, NORMS[asset_class]))
    for challenge in spec.verified_by:
        challenge_node = NORMS[f"CH-{challenge}"]
        graph.add((node, ARGOS.verifiedBy, challenge_node))
        graph.add((challenge_node, RDF.type, ARGOS.Challenge))
        graph.add((challenge_node, ARGOS.challengeId, Literal(challenge)))
    for equivalence in spec.equivalences:
        graph.add((node, ARGOS.equivalentTo, equivalence_node(equivalence)))
    if spec.verification_pending:
        graph.add((node, ARGOS.verificationPending, Literal(spec.verification_pending)))
    return graph


def compile_obligation(text: str) -> bytes:
    spec = parse_obligation(to_internal(read_editorial(text)))
    return obligation_graph(spec).serialize(format="turtle", encoding="utf-8")


def compile_file(path: Path) -> bytes:
    return compile_obligation(path.read_text(encoding="utf-8"))
