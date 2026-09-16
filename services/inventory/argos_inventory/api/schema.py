"""GraphQL schema of the inventory: node neighbourhood, selector and snapshots (ARG-029).

Read only, with no mutations. Pages are mandatory and bounded, and the operation depth is limited so
that no query walks the graph unbounded (deviation note ARG-029-030).
"""

import asyncio
import uuid
from typing import Any

import strawberry
from strawberry.extensions import QueryDepthLimiter
from strawberry.scalars import JSON
from strawberry.types import Info

from argos_inventory.api.pagination import after_key, after_offset, check_first, encode_cursor
from argos_inventory.api.selector import NODE_COLUMNS, Selector, compile_selector, parse_selector
from argos_inventory.graph.model import NODE_LABELS
from argos_inventory.graph.store import GraphStore

MAX_QUERY_DEPTH = 4
DEFAULT_PAGE_SIZE = 100

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
_SYSTEMS_OF_KIND = "MATCH (s:System {kind: $kind}) RETURN s.id"
_SNAPSHOT = (
    "SELECT label, taken_at, node_count, content_hash FROM argos.inventory_snapshots WHERE id = %s"
)
_SNAPSHOT_NODES = (
    "SELECT node_key, label, name, qualified_name, system_id, categories "
    "FROM argos.inventory_snapshot_nodes WHERE snapshot_id = %s AND node_key > %s "
    "ORDER BY node_key LIMIT %s"
)


@strawberry.type
class Node:
    key: str
    label: str
    name: str | None
    qualified_name: str | None
    system_id: str | None


@strawberry.type
class NodePage:
    items: list[Node]
    end_cursor: str | None
    has_next_page: bool


@strawberry.type
class Neighbor:
    edge: str
    direction: str
    node: Node


@strawberry.type
class NeighborPage:
    items: list[Neighbor]
    end_cursor: str | None
    has_next_page: bool


@strawberry.type
class NodeDetail:
    node: Node
    props: JSON
    neighbors: NeighborPage


@strawberry.type
class SnapshotNode:
    key: str
    label: str
    name: str | None
    qualified_name: str | None
    system_id: str | None
    categories: JSON


@strawberry.type
class SnapshotPage:
    id: str
    label: str
    taken_at: str
    node_count: int
    content_hash: str
    items: list[SnapshotNode]
    end_cursor: str | None
    has_next_page: bool


def _text_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _node(row: dict[str, Any]) -> Node:
    return Node(
        key=str(row["key"]),
        label=str(row["label"]),
        name=_text_or_none(row["name"]),
        qualified_name=_text_or_none(row["qualified_name"]),
        system_id=_text_or_none(row["system_id"]),
    )


def _node_detail(store: GraphStore, key: str, limit: int, offset: int) -> NodeDetail | None:
    with store.connection() as conn:
        for label in NODE_LABELS:  # one indexed lookup per label beats an unlabelled scan
            columns = (*NODE_COLUMNS, "props")
            found = store.query(_FIND_NODE.format(label=label), {"key": key}, columns, conn)
            if found:
                break
        else:
            return None
        cypher = _NEIGHBORS.format(label=label, offset=offset, limit=limit + 1)
        rows = store.query(cypher, {"key": key}, _NEIGHBOR_COLUMNS, conn)
    items = [
        Neighbor(edge=str(r["edge"]), direction=str(r["direction"]), node=_node(r))
        for r in rows[:limit]
    ]
    page = NeighborPage(
        items=items,
        end_cursor=encode_cursor(offset + len(items)) if items else None,
        has_next_page=len(rows) > limit,
    )
    return NodeDetail(node=_node(found[0]), props=found[0]["props"], neighbors=page)


def _resolve(store: GraphStore, selector: Selector, limit: int, after: str | None) -> NodePage:
    with store.connection() as conn:
        system_ids = None
        if selector.system_kind is not None:
            kinds = store.query(_SYSTEMS_OF_KIND, {"kind": selector.system_kind}, ("id",), conn)
            system_ids = [str(r["id"]) for r in kinds]
        cypher, params = compile_selector(selector, limit, after, system_ids)
        rows = store.query(cypher, params, NODE_COLUMNS, conn)
    items = [_node(r) for r in rows[:limit]]
    return NodePage(
        items=items,
        end_cursor=encode_cursor(items[-1].key) if items else None,
        has_next_page=len(rows) > limit,
    )


def _snapshot_page(
    store: GraphStore, snapshot_id: str, limit: int, after: str | None
) -> SnapshotPage | None:
    with store.connection() as conn:
        head = conn.execute(_SNAPSHOT, (snapshot_id,)).fetchone()
        if head is None:
            return None
        rows = conn.execute(_SNAPSHOT_NODES, (snapshot_id, after or "", limit + 1)).fetchall()
    items = [
        SnapshotNode(
            key=str(r[0]),
            label=str(r[1]),
            name=r[2],
            qualified_name=r[3],
            system_id=r[4],
            categories=r[5],
        )
        for r in rows[:limit]
    ]
    return SnapshotPage(
        id=snapshot_id,
        label=str(head[0]),
        taken_at=head[1].isoformat(),
        node_count=int(head[2]),
        content_hash=str(head[3]),
        items=items,
        end_cursor=encode_cursor(items[-1].key) if items else None,
        has_next_page=len(rows) > limit,
    )


def _store(info: Info[dict[str, Any], None]) -> GraphStore:
    store: GraphStore = info.context["store"]
    return store


@strawberry.type
class Query:
    @strawberry.field(  # type: ignore[untyped-decorator]
        description="A node by natural key with its paginated neighbourhood."
    )
    async def node(
        self,
        info: Info[dict[str, Any], None],
        key: str,
        first: int = DEFAULT_PAGE_SIZE,
        after: str | None = None,
    ) -> NodeDetail | None:
        limit, offset = check_first(first), after_offset(after)
        return await asyncio.to_thread(_node_detail, _store(info), key, limit, offset)

    @strawberry.field(  # type: ignore[untyped-decorator]
        description="Nodes matching a challenge DSL selector, ordered by key."
    )
    async def resolve_selector(
        self,
        info: Info[dict[str, Any], None],
        selector: JSON,
        first: int = DEFAULT_PAGE_SIZE,
        after: str | None = None,
    ) -> NodePage:
        if not isinstance(selector, dict):
            raise ValueError("selector must be a JSON object")
        parsed = parse_selector(selector)
        limit, start = check_first(first), after_key(after)
        return await asyncio.to_thread(_resolve, _store(info), parsed, limit, start)

    @strawberry.field(  # type: ignore[untyped-decorator]
        description="An immutable inventory snapshot, page by page."
    )
    async def snapshot(
        self,
        info: Info[dict[str, Any], None],
        id: str,  # noqa: A002 - the public argument name of the contract
        first: int = DEFAULT_PAGE_SIZE,
        after: str | None = None,
    ) -> SnapshotPage | None:
        try:
            snapshot_id = str(uuid.UUID(id))
        except ValueError:
            raise ValueError("invalid snapshot id") from None
        limit, start = check_first(first), after_key(after)
        return await asyncio.to_thread(_snapshot_page, _store(info), snapshot_id, limit, start)


def depth_limiter() -> QueryDepthLimiter:
    """A factory, not an instance: the extension is rebuilt for each request."""
    return QueryDepthLimiter(max_depth=MAX_QUERY_DEPTH)


def build_schema() -> strawberry.Schema:
    return strawberry.Schema(query=Query, extensions=[depth_limiter])
