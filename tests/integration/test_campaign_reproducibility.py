"""ARG-042/049 · coherence is measured on the campaign's snapshot, and a remediation on a new one.

Security review F09-02, SEC-036: the SHACL probes read the live graph, so the same campaign could
answer two things; and the remediation re-ran over the old snapshot, so a finding measured on the
inventory could never close.
"""

import asyncio
from typing import Any

import pytest

from argos_challenges.activities import ChallengeActivities
from argos_challenges.evaluator import evaluate
from argos_challenges.findings import open_or_recur, transition
from argos_challenges.seal import verify_seal
from argos_challenges.store import (
    campaign_record,
    create_campaign,
    persist_verdict,
    pin_campaign,
    save_units,
)
from argos_inventory.catalog.treatments import import_treatments
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore

from .inventory_helpers import probe_runner, scan_and_ingest, secret_store
from .test_remediation import _remediate, _status

pytestmark = pytest.mark.integration

MANAGER = "user:campaign-manager"
DPO = "user:0192b000-0000-7000-8000-00000000d0c0"
HEADER = b"id;name;legal_basis;retention;systems\n"


def _pinned(dsn: str, activities: ChallengeActivities, name: str) -> str:
    campaign_id = create_campaign(dsn, name, {}, MANAGER)
    snapshot = activities._snapshot(campaign_id)
    pin_campaign(
        dsn,
        campaign_id,
        snapshot_id=snapshot.id,
        snapshot_hash=snapshot.content_hash,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    return campaign_id


def _unit(campaign_id: str, system_id: str, probe: dict[str, Any], name: str) -> dict[str, Any]:
    return {
        "unit_id": f"{name:u<64}"[:64],
        "campaign_id": campaign_id,
        "challenge_id": name,
        "challenge_version": "1.0",
        "obligation": "OBL-RGPD-30-3",
        "system_id": system_id,
        "node_key": f"k-{name}",
        "probe": probe,
        "criterion": {"threshold": {"field": "count", "operator": "==", "value": 0}},
        "evidence": {"capture": ["counts"], "minimisation": "Solo recuentos."},
        "severity": "medium",
        "sampling": None,
        "needs_approval": False,
        "preconditions": [],
    }


def test_shacl_answers_the_same_for_a_campaign_whatever_the_graph_does(
    migrated_db: str,
) -> None:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")
    store = GraphStore(migrated_db)
    classify_new_columns(store, probe_runner(migrated_db), system_id)
    import_treatments(
        store, migrated_db, HEADER + b"T-001;Historia clinica;;;dev-source-postgres\n", DPO
    )
    activities = ChallengeActivities(migrated_db, secret_store())
    campaign_id = _pinned(migrated_db, activities, "Campaña de coherencia")
    shacl = {"kind": "shacl", "target": "argos", "statement": None, "params": {}}
    unit = _unit(campaign_id, system_id, shacl, "coh-treatment-legal-basis")
    before = activities._internal_probe(unit)
    assert before["data"]["count"] > 0
    # The client completes its record of processing: the live graph moves, the campaign does not.
    import_treatments(
        store,
        migrated_db,
        HEADER + b"T-001;Historia clinica;GDPR 9.2.h;15 years;dev-source-postgres\n",
        DPO,
    )
    assert activities._internal_probe(unit) == before


def test_an_inventory_finding_closes_once_fixed_and_the_remediation_is_sealed(
    migrated_db: str,
) -> None:
    system_id = scan_and_ingest(migrated_db, "dev-source-postgres")  # nothing classified yet
    store = GraphStore(migrated_db)
    activities = ChallengeActivities(migrated_db, secret_store())
    campaign_id = _pinned(migrated_db, activities, "Campaña del inventario")
    snapshot_id = campaign_record(migrated_db, campaign_id)["snapshot_id"]
    probe = {
        "kind": "inventory_query",
        "target": "argos",
        "statement": None,
        "params": {"query": "unclassified_columns", "snapshot_id": snapshot_id},
    }
    unit = _unit(campaign_id, system_id, probe, "coh-unclassified-columns")
    save_units(migrated_db, campaign_id, [unit])
    measured = activities._internal_probe(unit)
    verdict = evaluate(unit, measured)
    assert verdict.result == "non_compliant"
    verdict_id, _ = persist_verdict(migrated_db, campaign_id, unit, verdict)
    finding = open_or_recur(migrated_db, campaign_id, unit, verdict, verdict_id)
    transition(migrated_db, finding["id"], "in_remediation", DPO)
    transition(migrated_db, finding["id"], "pending_verification", DPO)

    # The fix: the unclassified columns leave the inventory (the client drops them at the source).
    store.execute(
        "MATCH (c:Column {system_id: $system}) SET c.missing = true", {"system": system_id}
    )
    summary = asyncio.run(_remediate(migrated_db, campaign_id))

    assert summary["closed"] == 1
    assert _status(migrated_db, finding["id"]) == "closed_compliant"
    remediation = campaign_record(migrated_db, summary["campaign_id"])
    assert remediation["snapshot_id"] != snapshot_id
    assert remediation["status"] == "sealed" and verify_seal(migrated_db, summary["campaign_id"])
