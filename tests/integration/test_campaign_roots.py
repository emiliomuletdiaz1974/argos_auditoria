"""ARG-063 · the campaign root is anchored once, with its leaf count and tree key."""

import hashlib

import psycopg
import pytest

from argos_challenges.store import create_campaign
from argos_evidence.roots import get_root, record_root, tree_for

pytestmark = pytest.mark.integration


def _artifacts(count: int) -> dict[str, bytes]:
    ids = [f"00000000-0000-4000-8000-{i:012d}" for i in range(count)]
    return {verdict_id: hashlib.sha256(verdict_id.encode()).digest() for verdict_id in ids}


def test_the_leaves_follow_the_verdict_id_order() -> None:
    artifacts = _artifacts(5)
    shuffled = dict(reversed(list(artifacts.items())))
    assert tree_for(shuffled).root == tree_for(artifacts).root
    assert tree_for(artifacts).levels[0] == tree_for(shuffled).levels[0]


def test_a_root_is_recorded_and_read_back(migrated_db: str) -> None:
    campaign_id = create_campaign(migrated_db, "Campaña con raíz", {}, "user:campaign-manager")
    tree = tree_for(_artifacts(7))
    record_root(migrated_db, campaign_id, tree, "campaigns/x/merkle-tree.json")
    stored = get_root(migrated_db, campaign_id)
    assert stored is not None
    assert stored.root == tree.root.hex()
    assert stored.leaf_count == 7
    assert stored.tree_key == "campaigns/x/merkle-tree.json"
    assert stored.leaf_order == "verdict_id"


def test_a_campaign_without_a_root_reads_as_none(migrated_db: str) -> None:
    campaign_id = create_campaign(migrated_db, "Campaña sin raíz", {}, "user:campaign-manager")
    assert get_root(migrated_db, campaign_id) is None


def test_a_root_is_written_once(migrated_db: str) -> None:
    campaign_id = create_campaign(migrated_db, "Campaña sellada", {}, "user:campaign-manager")
    record_root(migrated_db, campaign_id, tree_for(_artifacts(3)), "campaigns/y/tree.json")
    with pytest.raises(psycopg.errors.UniqueViolation):
        record_root(migrated_db, campaign_id, tree_for(_artifacts(4)), "campaigns/y/tree.json")
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE argos.campaign_roots SET leaf_count = 1")
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("DELETE FROM argos.campaign_roots")


def test_the_table_rejects_a_malformed_root(migrated_db: str) -> None:
    campaign_id = create_campaign(migrated_db, "Campaña rota", {}, "user:campaign-manager")
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO argos.campaign_roots (campaign_id, root, leaf_count, tree_key)"
            " VALUES (%s, 'zz', 1, 'k')",
            (campaign_id,),
        )
