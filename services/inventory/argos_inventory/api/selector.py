"""Compile a challenge DSL selector into parameterised Cypher (ARG-029, note ARG-029-030).

This is the only way the challenge engine reaches the graph. Labels come from the closed vocabulary
and every client value travels as a parameter: no client text is ever formatted into the query.
The fields `unclassified` and `status` let the ontology's asset classes say "column without a
classification" and "AI system pending confirmation" (deviation note ARG-031-033).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from argos_inventory.graph.model import NODE_LABELS

ALLOWED_SELECTOR_FIELDS = frozenset(
    {
        "label",
        "category",
        "system_kind",
        "min_confidence",
        "missing",
        "name_like",
        "unclassified",
        "status",
    }
)
MAX_TEXT_LENGTH = 100
DEFAULT_LABEL = "Column"
NODE_COLUMNS = ("key", "label", "name", "qualified_name", "system_id")
# AGE 1.5.0 does not accept RETURN aliases in ORDER BY, so the page is cut in a WITH first.
_RETURN = (
    "WITH DISTINCT n WITH n ORDER BY n.key LIMIT {limit} "
    "RETURN n.key AS node_key, label(n) AS node_label, n.name AS node_name, "
    "n.qualified_name AS node_qualified_name, coalesce(n.system_id, n.id) AS node_system_id"
)


@dataclass(frozen=True, slots=True)
class Selector:
    label: str = DEFAULT_LABEL
    category: str | None = None
    min_confidence: float | None = None
    missing: bool | None = None
    name_like: str | None = None
    system_kind: str | None = None
    unclassified: bool | None = None
    status: str | None = None


def _text(raw: Mapping[str, Any], field: str) -> str | None:
    if field not in raw:
        return None
    value = raw[field]
    if not isinstance(value, str) or not 0 < len(value) <= MAX_TEXT_LENGTH:
        raise ValueError(
            f"selector field {field} must be a text of 1 to {MAX_TEXT_LENGTH} characters"
        )
    return value


def _flag(raw: Mapping[str, Any], field: str) -> bool | None:
    value = raw.get(field)
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def parse_selector(raw: Mapping[str, Any]) -> Selector:
    unknown = set(raw) - ALLOWED_SELECTOR_FIELDS
    if unknown:
        raise ValueError(f"selector fields not allowed: {sorted(unknown)}")
    label = raw.get("label", DEFAULT_LABEL)
    if label not in NODE_LABELS:
        raise ValueError(f"unknown node label: {label!r}")
    category = _text(raw, "category")
    min_confidence = None
    if "min_confidence" in raw:
        if category is None:
            raise ValueError("min_confidence needs category")
        value = raw["min_confidence"]
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
            raise ValueError("min_confidence must be a number between 0 and 1")
        min_confidence = float(value)
    unclassified = _flag(raw, "unclassified")
    if unclassified is not None and category is not None:
        raise ValueError("unclassified and category cannot be combined")
    return Selector(
        label=str(label),
        category=category,
        min_confidence=min_confidence,
        missing=_flag(raw, "missing"),
        name_like=_text(raw, "name_like"),
        system_kind=_text(raw, "system_kind"),
        unclassified=unclassified,
        status=_text(raw, "status"),
    )


def compile_selector(
    selector: Selector,
    first: int,
    after: str | None = None,
    system_ids: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    match = f"MATCH (n:{selector.label})"  # label checked against NODE_LABELS by parse_selector
    where: list[str] = []
    params: dict[str, Any] = {}
    if after is not None:
        where.append("n.key > $after")
        params["after"] = after
    if selector.category is not None:
        match += "-[r:CLASSIFIED_AS]->(k:Category)"
        where.append("k.name STARTS WITH $category")
        params["category"] = selector.category
    if selector.min_confidence is not None:
        where.append("r.confidence >= $min_confidence")
        params["min_confidence"] = selector.min_confidence
    if selector.missing is not None:
        where.append("coalesce(n.missing, false) = $missing")
        params["missing"] = selector.missing
    if selector.name_like is not None:
        where.append("n.name STARTS WITH $name_like")
        params["name_like"] = selector.name_like
    if selector.unclassified is True:
        where.append("NOT exists((n)-[:CLASSIFIED_AS]->())")
    elif selector.unclassified is False:
        where.append("exists((n)-[:CLASSIFIED_AS]->())")
    if selector.status is not None:
        where.append("n.status STARTS WITH $status")
        params["status"] = selector.status
    if selector.system_kind is not None:
        if system_ids is None:
            raise ValueError("system_kind needs the system ids of that kind")
        where.append("coalesce(n.system_id, n.id) IN $system_ids")
        params["system_ids"] = sorted(system_ids)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    return f"{match}{clause} {_RETURN.format(limit=first + 1)}", params
