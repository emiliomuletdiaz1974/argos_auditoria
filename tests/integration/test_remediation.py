"""ARG-049 · the remediation is verified with the same challenge that found the problem."""

import asyncio
import uuid
from typing import Any

import psycopg
import pytest
from temporalio.client import Client
from temporalio.worker import Worker

from argos_challenges.activities import ChallengeActivities
from argos_challenges.evaluator import evaluate
from argos_challenges.findings import open_or_recur, transition
from argos_challenges.store import (
    create_campaign,
    grant_approval,
    persist_verdict,
    pin_campaign,
    save_units,
)
from argos_challenges.workflows import RemediationRun
from argos_common.config import get_config

from .inventory_helpers import secret_store
from .sources import register_catalog_system

pytestmark = pytest.mark.integration

MANAGER = "user:campaign-manager"
DPO = "user:dpo"
FIXED_CHECK = "encryption_at_rest"


def _unit(campaign_id: str, system_id: str, name: str, field: tuple[str, str]) -> dict[str, Any]:
    return {
        "unit_id": f"{name:b<64}"[:64],
        "campaign_id": campaign_id,
        "challenge_id": name,
        "challenge_version": "1.0",
        "obligation": "OBL-RGPD-32-3",
        "system_id": system_id,
        "node_key": f"k-{name}",
        "probe": {
            "kind": "check_config",
            "target": "clinic",
            "statement": None,
            "params": {"check": FIXED_CHECK},
        },
        "criterion": {"threshold": {"field": field[0], "operator": "==", "value": field[1]}},
        "evidence": {"capture": ["configuration"], "minimisation": "Solo parámetros de cifrado."},
        "severity": "high",
        "sampling": None,
        "needs_approval": False,
        "preconditions": [],
    }


@pytest.fixture
def pending(migrated_db: str) -> tuple[str, dict[str, str]]:
    """Two findings waiting for verification: one the client fixed, one it did not."""
    system_id = register_catalog_system(migrated_db, "dev-source-postgres")
    campaign_id = create_campaign(migrated_db, "Campaña original", {}, MANAGER)
    pin_campaign(
        migrated_db,
        campaign_id,
        snapshot_id=None,
        snapshot_hash=None,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    # The same probe answers both: password encryption is scram-sha-256 (met after the client's
    # fix) and ssl is still off (not met), with the shape the connector really returns.
    fields = {
        "sec-fixed": ("rows.1.setting", "scram-sha-256"),
        "sec-still-broken": ("rows.2.setting", "on"),
    }
    findings: dict[str, str] = {}
    for name, field in fields.items():
        unit = _unit(campaign_id, system_id, name, field)
        save_units(migrated_db, campaign_id, [unit])
        verdict = evaluate(unit, {"ok": True, "data": {"rows": [{"ssl": "off"}]}})
        verdict_id, _ = persist_verdict(migrated_db, campaign_id, unit, verdict)
        finding = open_or_recur(migrated_db, campaign_id, unit, verdict, verdict_id)
        transition(migrated_db, finding["id"], "in_remediation", DPO)
        transition(migrated_db, finding["id"], "pending_verification", DPO)
        findings[name] = finding["id"]
    return campaign_id, findings


async def _approve_remediation(dsn: str, origin: str) -> None:
    """The DPO approves every gate the remediation campaign of `origin` asks for."""
    while True:
        with psycopg.connect(dsn) as conn:
            rows = conn.execute(
                "SELECT r.campaign_id::text, r.gate FROM argos.approval_requests r "
                "JOIN argos.campaigns c ON c.id = r.campaign_id "
                "WHERE c.scope->>'campaign_id' = %s AND NOT EXISTS ("
                " SELECT 1 FROM argos.approvals a WHERE a.campaign_id = r.campaign_id"
                " AND a.gate = r.gate)",
                (origin,),
            ).fetchall()
        for campaign_id, gate in rows:
            grant_approval(dsn, campaign_id, gate, DPO, 1)
        await asyncio.sleep(0.5)


async def _remediate(dsn: str, campaign_id: str, *, approve: bool = True) -> dict[str, Any]:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    activities = ChallengeActivities(dsn, secret_store())
    queue = f"argos-remediation-test-{uuid.uuid4().hex[:8]}"
    approver = asyncio.create_task(_approve_remediation(dsn, campaign_id)) if approve else None
    try:
        async with Worker(
            client,
            task_queue=queue,
            workflows=[RemediationRun],
            activities=[
                activities.start_remediation,
                activities.request_approval,
                activities.check_gate,
                activities.set_campaign_status,
                activities.probe,
                activities.evaluate_unit,
                activities.transition_finding,
            ],
        ):
            return dict(
                await client.execute_workflow(
                    RemediationRun.run,
                    {"campaign_id": campaign_id, "requested_by": MANAGER},
                    id=f"remediation-{campaign_id}",
                    task_queue=queue,
                )
            )
    finally:
        if approver is not None:
            approver.cancel()


def _status(dsn: str, finding_id: str) -> str:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT status FROM argos.findings WHERE id = %s", (finding_id,)
        ).fetchone()
    assert row is not None
    return str(row[0])


@pytest.mark.asyncio
async def test_what_the_client_fixed_closes_and_what_it_did_not_reopens(
    migrated_db: str, pending: tuple[str, dict[str, str]]
) -> None:
    campaign_id, findings = pending
    summary = await _remediate(migrated_db, campaign_id)
    assert summary["verified"] == 2
    assert summary["closed"] == 1 and summary["reopened"] == 1
    assert _status(migrated_db, findings["sec-fixed"]) == "closed_compliant"
    assert _status(migrated_db, findings["sec-still-broken"]) == "reopened"


@pytest.mark.asyncio
async def test_the_reopened_finding_does_not_count_a_new_occurrence(
    migrated_db: str, pending: tuple[str, dict[str, str]]
) -> None:
    campaign_id, findings = pending
    await _remediate(migrated_db, campaign_id)
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT occurrences FROM argos.findings WHERE id = %s",
            (findings["sec-still-broken"],),
        ).fetchone()
    assert row is not None and int(row[0]) == 1


@pytest.mark.asyncio
async def test_the_remediation_runs_the_stored_unit_in_its_own_campaign(
    migrated_db: str, pending: tuple[str, dict[str, str]]
) -> None:
    campaign_id, _ = pending
    summary = await _remediate(migrated_db, campaign_id)
    assert summary["campaign_id"] != campaign_id
    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute(
            "SELECT challenge_id, challenge_version FROM argos.verdicts WHERE campaign_id = %s",
            (summary["campaign_id"],),
        ).fetchall()
    assert sorted(row[0] for row in rows) == ["sec-fixed", "sec-still-broken"]
    assert {row[1] for row in rows} == {"1.0"}  # the version that measured the problem


@pytest.mark.asyncio
async def test_without_pending_findings_there_is_nothing_to_verify(migrated_db: str) -> None:
    campaign_id = create_campaign(migrated_db, "Campaña sin hallazgos", {}, MANAGER)
    summary = await _remediate(migrated_db, campaign_id)
    assert summary == {
        "campaign_id": None,
        "verified": 0,
        "closed": 0,
        "reopened": 0,
        "unchanged": 0,
    }


@pytest.mark.asyncio
async def test_without_the_approval_of_a_dpo_nothing_is_probed(
    migrated_db: str, pending: tuple[str, dict[str, str]]
) -> None:
    """SEC-010: a campaign manager alone cannot re-run probes against the client."""
    campaign_id, findings = pending
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(_remediate(migrated_db, campaign_id, approve=False), timeout=15)
    with psycopg.connect(migrated_db) as conn:
        verdicts = conn.execute(
            "SELECT count(*) FROM argos.verdicts v JOIN argos.campaigns c ON c.id = v.campaign_id "
            "WHERE c.scope->>'campaign_id' = %s",
            (campaign_id,),
        ).fetchone()
    assert verdicts is not None and int(verdicts[0]) == 0
    assert _status(migrated_db, findings["sec-fixed"]) == "pending_verification"


def test_a_remediation_needs_the_person_who_asks_for_it(migrated_db: str) -> None:
    from temporalio.exceptions import ApplicationError

    activities = ChallengeActivities(migrated_db, secret_store())
    with pytest.raises(ApplicationError, match="person"):
        activities._start_remediation({"campaign_id": str(uuid.uuid4())})
