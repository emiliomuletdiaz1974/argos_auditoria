"""ARG-066 · the journal head anchored in the signed campaign root, and its WORM report."""

import ast
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path

import boto3
import psycopg
import pytest

import argos_evidence.journal as evidence_journal
from argos_challenges.seal import seal_campaign
from argos_challenges.store import create_campaign
from argos_common.journal import compute_hash
from argos_common.journal_pg import PostgresJournal
from argos_common.release import VaultTransitSigner
from argos_evidence.artifacts import verify_artifact
from argos_evidence.journal import (
    JournalAnchorError,
    anchor_head,
    journal_report,
    report_key,
    verify_anchor,
)
from argos_evidence.merkle import build_tree
from argos_evidence.roots import record_root
from argos_evidence.signing import sign_campaign_root
from argos_evidence.worm import WormStore, ensure_buckets

pytestmark = pytest.mark.integration

VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")


def _store() -> WormStore:
    client = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:7075",
        aws_access_key_id="dev-only-evidence",
        aws_secret_access_key="dev-only-evidence-secret",  # noqa: S106 - development store
        region_name="us-east-1",
    )
    ensure_buckets(client, default_retention_days=1)
    return WormStore(client)


def _until() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)


def _sealed_campaign(dsn: str) -> str:
    campaign_id = create_campaign(dsn, "Campaña anclada", {}, "user:campaign-manager")
    seal_campaign(dsn, campaign_id)
    leaves = [hashlib.sha256(uuid.uuid4().bytes).digest() for _ in range(2)]
    record_root(dsn, campaign_id, build_tree(leaves), f"campaigns/{campaign_id}/tree.json")
    return campaign_id


def _write(dsn: str, count: int) -> None:
    journal = PostgresJournal(dsn)
    for i in range(count):
        journal.append("system:test", "test.write", {"i": i})


def _tamper(dsn: str, seq: int, rewrite_chain: bool) -> None:
    """A malicious administrator edits one entry and, if asked, recomputes every hash after it."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("ALTER TABLE argos.audit_journal DISABLE TRIGGER journal_no_update")
        conn.execute(
            "UPDATE argos.audit_journal SET payload_canon = '{\"i\":999}' WHERE seq = %s", (seq,)
        )
        if rewrite_chain:
            rows = conn.execute(
                "SELECT seq, at_canon, actor, action, payload_canon, prev_hash"
                " FROM argos.audit_journal WHERE seq >= %s ORDER BY seq",
                (seq,),
            ).fetchall()
            prev = bytes(rows[0][5])
            for row_seq, at_canon, actor, action, payload, _ in rows:
                entry = compute_hash(row_seq, at_canon, actor, action, payload, prev)
                conn.execute(
                    "UPDATE argos.audit_journal SET prev_hash = %s, entry_hash = %s WHERE seq = %s",
                    (prev, entry, row_seq),
                )
                prev = entry
        conn.execute("ALTER TABLE argos.audit_journal ENABLE TRIGGER journal_no_update")


def test_the_anchored_head_is_the_current_verified_head(migrated_db: str) -> None:
    _write(migrated_db, 5)
    head = anchor_head(migrated_db)
    seq, entry_hash = PostgresJournal(migrated_db).head()
    assert head == {"seq": seq, "entry_hash": entry_hash.hex()}
    assert verify_anchor(migrated_db, head).intact


def test_a_broken_journal_is_never_anchored(migrated_db: str) -> None:
    _write(migrated_db, 10)
    _tamper(migrated_db, 4, rewrite_chain=False)
    with pytest.raises(JournalAnchorError, match="4"):
        anchor_head(migrated_db)


def test_editing_an_entry_before_the_anchor_is_detected(migrated_db: str) -> None:
    _write(migrated_db, 10)
    head = anchor_head(migrated_db)
    _tamper(migrated_db, 3, rewrite_chain=False)
    check = verify_anchor(migrated_db, head)
    assert not check.intact
    assert check.anomalies[0].seq == 3


def test_rewriting_the_whole_history_is_detected_by_the_anchor(migrated_db: str) -> None:
    _write(migrated_db, 10)
    head = anchor_head(migrated_db)
    _tamper(migrated_db, 3, rewrite_chain=True)
    assert PostgresJournal(migrated_db).verify().intact  # the chain alone no longer tells
    check = verify_anchor(migrated_db, head)
    assert not check.intact
    assert not check.head_matches


def test_signing_anchors_the_head_by_default(migrated_db: str) -> None:
    campaign_id = _sealed_campaign(migrated_db)
    store = _store()
    signer = VaultTransitSigner(VAULT, "root", key="argos-evidence")
    head = anchor_head(migrated_db)
    record = sign_campaign_root(migrated_db, store, signer, campaign_id, None, _until())
    payload = json.loads(store.get(record.key, record.version_id))["payload"]
    assert payload["journal_head"] == head
    assert verify_anchor(migrated_db, payload["journal_head"]).intact


def test_the_report_is_a_verifiable_artifact_in_the_worm(migrated_db: str) -> None:
    _write(migrated_db, 3)
    campaign_id = create_campaign(migrated_db, "Campaña con informe", {}, "user:campaign-manager")
    store = _store()
    head = anchor_head(migrated_db)
    record = journal_report(migrated_db, store, campaign_id, head, _until())
    assert record.key == report_key(campaign_id)
    body = store.get(record.key, record.version_id)
    assert verify_artifact(body)
    report = json.loads(body)
    assert report["intact"] is True
    assert report["anchored_head"] == head
    assert report["verified_entries"] == head["seq"]
    assert journal_report(migrated_db, store, campaign_id, head, _until()) == record


def test_there_is_no_second_journal_hash_formula() -> None:
    tree = ast.parse(Path(evidence_journal.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "hashlib" not in imported
    assert "compute_hash" not in imported | names | attributes
