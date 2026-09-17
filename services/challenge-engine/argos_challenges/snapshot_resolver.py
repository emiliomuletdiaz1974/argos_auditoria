"""Selector resolution over a pinned snapshot (ARG-042, protocol of ARG-039).

A campaign measures against the snapshot it pinned, not against the live graph: that is what makes
two runs of the same campaign comparable. This resolver answers the same selectors as the inventory
API — same fields, same semantics — reading the rows of the snapshot instead of querying AGE, and an
integration test checks that both give the same nodes for every asset class.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg

from argos_inventory.api.selector import Selector
from argos_inventory.versioning.snapshots import snapshot_nodes
from argos_ontology.resolver import ResolvedNode

_SYSTEMS_OF_KIND = "SELECT id::text FROM argos.systems WHERE kind = %s"


def _classified(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    categories = node.get("categories") or []
    return [entry for entry in categories if isinstance(entry, Mapping)]


def matches(node: Mapping[str, Any], selector: Selector, system_ids: frozenset[str] | None) -> bool:
    """Whether a snapshot row answers the selector, with the semantics of the inventory API."""
    if str(node.get("label")) != selector.label:
        return False
    if selector.missing is True:
        return False  # a snapshot only keeps what was present when it was taken
    if selector.name_like is not None and not str(node.get("name") or "").startswith(
        selector.name_like
    ):
        return False
    if selector.status is not None and not str(node.get("status") or "").startswith(
        selector.status
    ):
        return False
    if system_ids is not None and str(node.get("system_id")) not in system_ids:
        return False
    categories = _classified(node)
    if selector.unclassified is True and categories:
        return False
    if selector.unclassified is False and not categories:
        return False
    if selector.category is None:
        return True
    for entry in categories:
        if not str(entry.get("category", "")).startswith(selector.category):
            continue
        if selector.min_confidence is None:
            return True
        confidence = entry.get("confidence")
        if confidence is not None and float(confidence) >= selector.min_confidence:
            return True
    return False


class SnapshotSelectorResolver:
    """Resolves selectors over a snapshot; fulfils the `SelectorResolver` protocol of F04-11."""

    def __init__(
        self, dsn: str, snapshot_id: str, nodes: Sequence[Mapping[str, Any]] | None = None
    ):
        self._dsn = dsn
        self.snapshot_id = snapshot_id
        self._nodes = list(nodes) if nodes is not None else snapshot_nodes(dsn, snapshot_id)
        self._kinds: dict[str, frozenset[str]] = {}

    @property
    def nodes(self) -> list[Mapping[str, Any]]:
        return list(self._nodes)

    def _systems_of_kind(self, kind: str) -> frozenset[str]:
        if kind not in self._kinds:
            with psycopg.connect(self._dsn) as conn:
                rows = conn.execute(_SYSTEMS_OF_KIND, (kind,)).fetchall()
            self._kinds[kind] = frozenset(str(row[0]) for row in rows)
        return self._kinds[kind]

    def resolve(self, selector: Selector) -> list[ResolvedNode]:
        allowed = (
            None if selector.system_kind is None else self._systems_of_kind(selector.system_kind)
        )
        found = [
            ResolvedNode(
                str(node["node_key"]),
                None if node.get("system_id") is None else str(node["system_id"]),
            )
            for node in self._nodes
            if matches(node, selector, allowed)
        ]
        return sorted(found)
