"""Reading a node and its neighbourhood (ARG-021, ARG-029).

The Cypher lives here and only here: the GraphQL schema dresses these rows in its types and the v1
API returns them as JSON. Two shapes, one query, so neither can drift from the other.
"""

from typing import Any

from argos_inventory.graph.model import NODE_LABELS
from argos_inventory.graph.store import GraphStore

NODE_COLUMNS = ("key", "label", "name", "qualified_name", "system_id")
_NODE_FIELDS = (
    "n.key AS node_key, label(n) AS node_label, n.name AS node_name, "
    "n.qualified_name AS node_qualified_name, coalesce(n.system_id, n.id) AS node_system_id"
)
_FIND_NODE = "MATCH (n:{label} {{key: $key}}) RETURN " + _NODE_FIELDS + ", properties(n) AS props"
_NEIGHBORS = (
    "MATCH (n:{label} {{key: $key}})-[e]-(m) "
    "RETURN label(e) AS edge, CASE WHEN start_id(e) = id(n) THEN 'out' ELSE 'in' END AS direction, "
    "m.key AS node_key, label(m) AS node_label, m.name AS node_name, "
    "m.qualified_name AS node_qualified_name, coalesce(m.system_id, m.id) AS node_system_id "
    "ORDER BY m.key, label(e), start_id(e) SKIP {offset} LIMIT {limit}"
)
_NEIGHBOR_COLUMNS = ("edge", "direction", *NODE_COLUMNS)


def node_detail(store: GraphStore, key: str, limit: int, offset: int = 0) -> dict[str, Any] | None:
    """The node, its properties and a page of neighbours; `has_more` says if there are others."""
    with store.connection() as conn:
        for label in NODE_LABELS:  # one indexed lookup per label beats an unlabelled scan
            found = store.query(
                _FIND_NODE.format(label=label), {"key": key}, (*NODE_COLUMNS, "props"), conn
            )
            if found:
                break
        else:
            return None
        cypher = _NEIGHBORS.format(label=label, offset=offset, limit=limit + 1)
        rows = store.query(cypher, {"key": key}, _NEIGHBOR_COLUMNS, conn)
    return {
        "node": found[0],
        "props": found[0]["props"],
        "neighbours": rows[:limit],
        "has_more": len(rows) > limit,
    }
