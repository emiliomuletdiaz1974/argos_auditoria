"""Anchor of each campaign's Merkle root (ARG-063).

Leaves are ordered by ascending ``verdict_id`` (its canonical text form): the
order is stable and documented so anyone can rebuild the same tree from the
artifacts. The full tree lives in the WORM store; this table keeps its root,
its leaf count and its key, and is written once.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import psycopg

from argos_evidence.merkle import MerkleTree, build_tree

LEAF_ORDER = "verdict_id"


@dataclass(frozen=True)
class CampaignRoot:
    campaign_id: str
    root: str
    leaf_count: int
    tree_key: str
    leaf_order: str


def tree_for(artifacts: Mapping[str, bytes]) -> MerkleTree:
    """Tree over ``{verdict_id: artifact sha256}``, leaves in verdict_id order."""
    return build_tree([artifacts[verdict_id] for verdict_id in sorted(artifacts)])


def record_root(dsn: str, campaign_id: str, tree: MerkleTree, tree_key: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.campaign_roots (campaign_id, root, leaf_count, tree_key, leaf_order)"
            " VALUES (%s, %s, %s, %s, %s)",
            (campaign_id, tree.root.hex(), tree.size, tree_key, LEAF_ORDER),
        )


def get_root(dsn: str, campaign_id: str) -> CampaignRoot | None:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT campaign_id, root, leaf_count, tree_key, leaf_order"
            " FROM argos.campaign_roots WHERE campaign_id = %s",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return CampaignRoot(str(row[0]), str(row[1]), int(row[2]), str(row[3]), str(row[4]))
