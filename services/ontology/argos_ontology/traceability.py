"""Obligation-challenge traceability matrix: quality control and coverage map (ARG-037).

Every published obligation needs at least one challenge from the catalog or an explicit pending
reason, and every catalog challenge needs an obligation. The matrix is a reproducible query over
ontology and catalog: the editorial CI fails on its errors and the console shows its rows.
"""

import csv
import io
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
from rdflib import RDF, RDFS, Graph, URIRef

from argos_ontology.editorial.compiler import CHALLENGE_ID
from argos_ontology.vocabulary import ARGOS, EVIDENCE_TYPES, LIBRARY_DIR, bind_prefixes

CATALOG_FILE = LIBRARY_DIR / "challenges" / "catalog.yaml"
ONTOLOGY_PATTERNS = ("ontology/**/*.ttl",)
STATUSES = ("covered", "pending", "orphan")
CSV_COLUMNS = ("obligation", "label", "severity", "challenges", "status", "pending_reason")


@dataclass(frozen=True, slots=True)
class ChallengeEntry:
    id: str
    family: str
    evidence_type: str
    description: str


@dataclass(frozen=True, slots=True)
class TraceabilityRow:
    obligation: str
    label: str
    severity: str | None
    challenges: tuple[str, ...]
    status: str
    pending_reason: str | None


def library_graph(library_dir: Path = LIBRARY_DIR) -> Graph:
    graph = bind_prefixes(Graph())
    for pattern in ONTOLOGY_PATTERNS:
        for path in sorted(library_dir.glob(pattern)):
            graph.parse(path, format="turtle")
    return graph


def parse_challenge_catalog(document: Any) -> dict[str, ChallengeEntry]:
    if not isinstance(document, Mapping) or not isinstance(document.get("challenges"), list):
        raise ValueError("the challenge catalog must have a 'challenges' list")
    catalog: dict[str, ChallengeEntry] = {}
    for item in document["challenges"]:
        if not isinstance(item, Mapping):
            raise ValueError("every catalog entry must be a mapping")
        missing = [f for f in ("id", "family", "evidence_type", "description") if not item.get(f)]
        if missing:
            raise ValueError(f"catalog entry {item.get('id')!r} misses {missing}")
        entry = ChallengeEntry(
            str(item["id"]),
            str(item["family"]),
            str(item["evidence_type"]),
            str(item["description"]),
        )
        if not CHALLENGE_ID.match(entry.id):
            raise ValueError(f"invalid challenge id in catalog: {entry.id!r}")
        if entry.evidence_type not in EVIDENCE_TYPES:
            raise ValueError(f"unknown evidence type for {entry.id}: {entry.evidence_type!r}")
        if entry.id in catalog:
            raise ValueError(f"repeated challenge id in catalog: {entry.id}")
        catalog[entry.id] = entry
    return dict(sorted(catalog.items()))


def load_challenge_catalog(path: Path = CATALOG_FILE) -> dict[str, ChallengeEntry]:
    return parse_challenge_catalog(yaml.safe_load(path.read_text(encoding="utf-8")))


def _text(graph: Graph, subject: URIRef, predicate: URIRef) -> str | None:
    value = graph.value(subject, predicate)
    return None if value is None else str(value)


def build_matrix(
    graph: Graph, catalog: Mapping[str, ChallengeEntry]
) -> tuple[list[TraceabilityRow], list[str]]:
    """Rows sorted by obligation IRI and the errors that must block a publication."""
    rows: list[TraceabilityRow] = []
    errors: list[str] = []
    referenced: set[str] = set()
    obligations = sorted(
        s for s in graph.subjects(RDF.type, ARGOS.Obligation) if isinstance(s, URIRef)
    )
    for obligation in obligations:
        name = str(obligation)
        challenges: list[str] = []
        for challenge in sorted(graph.objects(obligation, ARGOS.verifiedBy), key=str):
            challenge_id = graph.value(challenge, ARGOS.challengeId)
            if challenge_id is None:
                errors.append(f"{name}: challenge {challenge} has no challengeId")
                continue
            challenges.append(str(challenge_id))
        pending = _text(graph, obligation, ARGOS.verificationPending)
        for used in challenges:
            if used not in catalog:
                errors.append(f"{name}: challenge not in catalog: {used}")
        if challenges and pending:
            errors.append(f"{name}: has challenges and a verificationPending reason at once")
        if not challenges and not pending:
            errors.append(f"{name}: obligation without challenge or verificationPending reason")
        referenced.update(challenges)
        status = "covered" if challenges else "pending" if pending else "orphan"
        rows.append(
            TraceabilityRow(
                obligation=name,
                label=_text(graph, obligation, RDFS.label) or name,
                severity=_text(graph, obligation, ARGOS.severity),
                challenges=tuple(sorted(set(challenges))),
                status=status,
                pending_reason=pending,
            )
        )
    for unused in sorted(set(catalog) - referenced):
        errors.append(f"orphan challenge without obligation: {unused}")
    return rows, errors


def matrix_json(rows: list[TraceabilityRow]) -> str:
    return (
        json.dumps([asdict(r) for r in rows], ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    )


def matrix_csv(rows: list[TraceabilityRow]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            (
                row.obligation,
                row.label,
                row.severity or "",
                ",".join(row.challenges),
                row.status,
                row.pending_reason or "",
            )
        )
    return buffer.getvalue()
