"""Applicability plane: asset classes of the ontology and their inventory selectors (ARG-033).

The mapping between abstract classes ("stored health data") and graph nodes lives in the ontology,
inside the editorial cycle, never in Python: each AssetClass carries the selector JSON that the
inventory API resolves (deviation note ARG-031-033).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rdflib import RDF, Graph, URIRef

from argos_inventory.api.selector import Selector, parse_selector
from argos_ontology.vocabulary import ARGOS, LIBRARY_DIR, bind_prefixes

ASSET_CLASSES_FILE = LIBRARY_DIR / "ontology" / "asset-classes" / "base.ttl"


@dataclass(frozen=True, slots=True)
class AssetClass:
    iri: URIRef
    graph_label: str | None
    selector: dict[str, Any] | None
    verification_pending: str | None
    data_category: URIRef | None


def load_asset_classes(path: Path = ASSET_CLASSES_FILE) -> Graph:
    return bind_prefixes(Graph().parse(path, format="turtle"))


def _text(graph: Graph, subject: URIRef, predicate: URIRef) -> str | None:
    value = graph.value(subject, predicate)
    return None if value is None else str(value)


def asset_classes(graph: Graph) -> list[AssetClass]:
    """Every argos:AssetClass in the graph; a selector that is not a JSON object is kept as None."""
    found: list[AssetClass] = []
    for subject in sorted(
        s for s in graph.subjects(RDF.type, ARGOS.AssetClass) if isinstance(s, URIRef)
    ):
        raw = _text(graph, subject, ARGOS.selectorJson)
        selector: dict[str, Any] | None = None
        if raw is not None:
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            selector = parsed if isinstance(parsed, dict) else None
        category = graph.value(subject, ARGOS.dataCategory)
        found.append(
            AssetClass(
                iri=subject,
                graph_label=_text(graph, subject, ARGOS.graphLabel),
                selector=selector,
                verification_pending=_text(graph, subject, ARGOS.verificationPending),
                data_category=category if isinstance(category, URIRef) else None,
            )
        )
    return found


def compiled_selector(asset_class: AssetClass) -> Selector:
    if asset_class.selector is None:
        raise ValueError(f"{asset_class.iri} has no usable selector")
    return parse_selector(asset_class.selector)


def asset_class_errors(graph: Graph) -> list[str]:
    """Problems that make an asset class unusable by the resolver; empty when all are sound."""
    errors: list[str] = []
    for asset_class in asset_classes(graph):
        name = str(asset_class.iri)
        raw = _text(graph, asset_class.iri, ARGOS.selectorJson)
        if raw is None:
            if asset_class.verification_pending is None:
                errors.append(f"{name}: no selector and no verificationPending reason")
            continue
        if asset_class.selector is None:
            errors.append(f"{name}: selectorJson is not a JSON object")
            continue
        try:
            selector = parse_selector(asset_class.selector)
        except ValueError as exc:
            errors.append(f"{name}: invalid selector: {exc}")
            continue
        if asset_class.graph_label != selector.label:
            errors.append(
                f"{name}: graphLabel {asset_class.graph_label!r} differs from selector label "
                f"{selector.label!r}"
            )
    return errors
