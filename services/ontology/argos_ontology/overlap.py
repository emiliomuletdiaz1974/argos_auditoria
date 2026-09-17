"""Overlap matrix between norms: one control, verdicts for several obligations (ARG-038).

An asset class reached by obligations of two or more norms is where a single campaign produces
evidence for all of them (a health data access log serves GDPR and EHDS). The matrix is a
reproducible query over the library, published with every editorial release next to the
traceability matrix; declared equivalences (argos:equivalentTo) travel with each row.
"""

import csv
import io
import json
from collections import defaultdict
from dataclasses import asdict, dataclass

from rdflib import RDF, Graph, URIRef

from argos_ontology.vocabulary import ARGOS, NORMS

CSV_COLUMNS = ("asset_class", "norms", "obligations", "equivalences")


@dataclass(frozen=True, slots=True)
class OverlapRow:
    asset_class: str
    norms: tuple[str, ...]
    obligations: tuple[str, ...]
    equivalences: tuple[str, ...]


def _short(node: object) -> str:
    return str(node).removeprefix(str(NORMS))


def _norm_of(graph: Graph, obligation: URIRef) -> str | None:
    for article in graph.objects(obligation, ARGOS.derivesFrom):
        norm = graph.value(article, ARGOS.partOf)
        if isinstance(norm, URIRef) and (norm, RDF.type, ARGOS.Norm) in graph:
            return _short(norm)
    return None


def build_overlap(graph: Graph) -> list[OverlapRow]:
    """Asset classes with obligations of several norms, sorted by class."""
    by_class: dict[str, dict[str, str]] = defaultdict(dict)
    equivalences: dict[str, list[str]] = defaultdict(list)
    for obligation in graph.subjects(RDF.type, ARGOS.Obligation):
        if not isinstance(obligation, URIRef):
            continue
        norm = _norm_of(graph, obligation)
        if norm is None:
            continue
        name = _short(obligation)
        for target in graph.objects(obligation, ARGOS.appliesTo):
            by_class[_short(target)][name] = norm
        equivalences[name] = sorted(
            f"{name}={_short(e)}" for e in graph.objects(obligation, ARGOS.equivalentTo)
        )
    rows = []
    for asset_class in sorted(by_class):
        obligations = by_class[asset_class]
        norms = tuple(sorted(set(obligations.values())))
        if len(norms) < 2:
            continue
        names = tuple(sorted(obligations))
        rows.append(
            OverlapRow(
                asset_class=asset_class,
                norms=norms,
                obligations=names,
                equivalences=tuple(e for n in names for e in equivalences[n]),
            )
        )
    return rows


def overlap_json(rows: list[OverlapRow]) -> str:
    return (
        json.dumps([asdict(r) for r in rows], ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    )


def overlap_csv(rows: list[OverlapRow]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            (
                row.asset_class,
                ",".join(row.norms),
                ",".join(row.obligations),
                ",".join(row.equivalences),
            )
        )
    return buffer.getvalue()
