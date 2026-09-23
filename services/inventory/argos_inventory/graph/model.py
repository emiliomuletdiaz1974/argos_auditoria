"""Closed vocabulary of the inventory graph and deterministic natural keys (ARG-021).

Every layer shares this list: a new label is a label the ontology (phase 4) and the challenges
(phase 5) must know. Classification is an edge to a Category node, never a node label.
"""

import hashlib

NODE_LABELS = (
    "System",
    "Schema",
    "Table",
    "Column",
    "FileArea",
    "Identity",
    "Group",
    "AISystem",
    "Treatment",
    "Category",
)
EDGE_LABELS = (
    "CONTAINS",
    "CAN_ACCESS",
    "MEMBER_OF",
    "FLOWS_TO",
    "CLASSIFIED_AS",
    "DECLARED_IN",
    "USES_MODEL",
    "OBSERVED",
)
# Root categories; phase 4 links them to obligations.
CATEGORIES = (
    "personal_data",
    "special_category.health",
    "special_category.other",
    "official_identifier",
    "financial_data",
    "contact_data",
    "location_data",
    "technical_credential",
    "no_personal_data",
)
KEY_SEPARATOR = "\x1f"


def natural_key(*parts: str) -> str:
    """Deterministic natural key of a node: what makes every upsert idempotent."""
    if not parts:
        raise ValueError("a natural key needs at least one part")
    # A name of the client may hold the separator: it is escaped, never refused, so the node is
    # not dropped from the inventory and two different names never share a key (SEC-024).
    escaped = [_escape(part) for part in parts]
    return hashlib.sha256(KEY_SEPARATOR.join(escaped).encode("utf-8")).hexdigest()[:40]


def _escape(part: str) -> str:
    """Injective: the backslash first, then the separator."""
    return part.replace("\\", "\\\\").replace(KEY_SEPARATOR, "\\x1f")


def system_key(system_id: str) -> str:
    return natural_key("S", system_id)


def schema_key(system_id: str, schema: str) -> str:
    return natural_key("H", system_id, schema)


def table_key(system_id: str, schema: str, table: str) -> str:
    return natural_key("T", system_id, schema, table)


def column_key(system_id: str, schema: str, table: str, column: str) -> str:
    return natural_key("C", system_id, schema, table, column)


def identity_key(system_id: str, name: str) -> str:
    return natural_key("I", system_id, name)


def group_key(system_id: str, name: str) -> str:
    return natural_key("G", system_id, name)


def file_area_key(system_id: str, path: str) -> str:
    return natural_key("F", system_id, path)


def ai_system_key(system_id: str, name: str) -> str:
    return natural_key("A", system_id, name)


def treatment_key(treatment_id: str) -> str:
    return natural_key("R", treatment_id)


def category_key(name: str) -> str:
    if name not in CATEGORIES:
        raise ValueError(f"unknown category: {name!r}")
    return natural_key("K", name)
