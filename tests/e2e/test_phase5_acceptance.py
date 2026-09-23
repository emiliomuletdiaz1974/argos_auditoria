"""Phase 5 acceptance test (Plan Director §8.2 "Fase 05").

1. A full campaign against the demonstration environment with the shipped library (more than
   fifteen challenges of two norms), with the synthetic subject injected by the client script.
2. The `start` and `sampling` gates approved by a DPO, with double control on `sampling`.
3. Verdicts and findings exactly the ones of the campaign ground truth (F05-01), planted ones
   included, and the aggregate per system the expected one.
4. A second campaign on the same snapshot gives the same `verdict_hash` for every unit.
5. The seal verifies; touching a verdict breaks it.
6. Remediation: what the client fixed closes, what it did not reopens.

The ground truth is never adjusted to the output: it is loaded from the fixture and compared.
"""

import asyncio
import contextlib
import os
import uuid
from collections import defaultdict
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fixtures.campaign_ground_truth import CampaignTruth, ExpectedVerdict, load_campaign_truth
from fixtures.campaign_ground_truth import worst as worst_of
from fixtures.demo_review import apply_demo_review
from integration.conftest import ADMIN_DSN, MIGRATIONS_DIR
from integration.inventory_helpers import probe_runner, scan_and_ingest, secret_store
from psycopg import sql
from temporalio.client import Client
from temporalio.worker import Worker

from argos_challenges.activities import ChallengeActivities
from argos_challenges.findings import transition
from argos_challenges.seal import verify_seal
from argos_challenges.store import (
    CampaignStateError,
    campaign_record,
    create_campaign,
    grant_approval,
    request_approval,
)
from argos_challenges.synthetic import (
    authorize_injection,
    confirm_exercise,
    confirm_injection,
    generate_subjects,
    register_subjects,
)
from argos_challenges.workflows import CampaignWorkflow, RemediationRun, SystemRun
from argos_common.config import get_config
from argos_common.migrations import apply_migrations
from argos_common.release import VaultTransitSigner
from argos_inventory.ai_discovery.detect import discover_ai
from argos_inventory.catalog.treatments import import_treatments
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.store import GraphStore
from argos_ontology.bundle import publish_library
from argos_ontology.vocabulary import LIBRARY_DIR, NORMS

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
TREATMENTS = REPO / "deploy" / "dev" / "ropa" / "treatments.csv"
TRUTH: CampaignTruth = load_campaign_truth()
ONTOLOGY_VERSION = "1.0.0"
IN_FORCE = date(2024, 8, 1)
MANAGER = "user:campaign-manager"
DPO = "user:dpo"
SECOND_DPO = "user:dpo-2"
SEED = "demo-campaign"


@pytest.fixture(scope="module")
def phase5_db() -> Iterator[str]:
    name = f"argos_phase5_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        dsn = f"{ADMIN_DSN.rsplit('/', 1)[0]}/{name}"
        apply_migrations(dsn, MIGRATIONS_DIR)
        yield dsn
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
            conn.execute(drop.format(sql.Identifier(name)))


@pytest.fixture(scope="module", autouse=True)
def _clean_sources() -> Iterator[None]:
    """The sources are shared by every test: leave them as the ground truth describes them."""
    subject = generate_subjects(SEED, 1)[0]
    _demo_client().revert(subject)
    try:
        yield
    finally:
        _demo_client().revert(subject)


@pytest.fixture(scope="module")
def demo(phase5_db: str) -> dict[str, str]:
    """The demonstration snapshot: both sources, the record of processing and the subject."""
    store = GraphStore(phase5_db)
    systems = {}
    for name in TRUTH.systems:
        systems[name] = scan_and_ingest(phase5_db, name)
        classify_new_columns(store, probe_runner(phase5_db), systems[name])
    discover_ai(store)
    apply_demo_review(store, phase5_db, systems)
    import_treatments(store, phase5_db, TREATMENTS.read_bytes(), DPO)
    # The campaign runs from signed content only (SEC-011): the library is published as a bundle.
    publish_library(
        phase5_db,
        LIBRARY_DIR,
        ONTOLOGY_VERSION,
        IN_FORCE,
        VaultTransitSigner(
            os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200"), "root", key="argos-content"
        ),
    )
    _inject_the_subject(phase5_db, systems)
    return systems


def _demo_client() -> Any:
    """The client side of the demonstration, never the product: loaded by path because `tools/`
    is a directory of scripts, not a package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "demo_client_actions", REPO / "tools" / "demo_client_actions.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inject_the_subject(dsn: str, systems: dict[str, str]) -> None:
    """ARGOS authorises and records; the client script injects and exercises (ADR-0008)."""
    client = _demo_client()
    subject = generate_subjects(SEED, 1)[0]
    register_subjects(dsn, None, [subject])
    client.inject(subject)
    for name, point in (
        ("dev-source-postgres", "clinic.patients"),
        ("dev-source-mariadb", "billing.patient_mirror"),
    ):
        injection = authorize_injection(
            dsn, subject.id, systems[name], point, "INSERT", "DELETE por id", DPO
        )
        confirm_injection(dsn, injection, "user:client-dba")
        if name == "dev-source-postgres":
            client.exercise_erasure(subject)
            confirm_exercise(dsn, injection, "erasure", "user:client-dba")
            confirm_exercise(dsn, injection, "access", "user:client-dba")


async def _run(dsn: str, campaign_id: str) -> dict[str, Any]:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    activities = ChallengeActivities(dsn, secret_store())
    queue = f"argos-phase5-{uuid.uuid4().hex[:8]}"
    async with Worker(
        client,
        task_queue=queue,
        workflows=[CampaignWorkflow, SystemRun],
        activities=[
            activities.prepare_campaign,
            activities.request_approval,
            activities.check_gate,
            activities.set_campaign_status,
            activities.probe,
            activities.wait_window,
            activities.evaluate_unit,
            activities.seal,
        ],
    ):
        handle = await client.start_workflow(
            CampaignWorkflow.run, campaign_id, id=f"campaign-{campaign_id}", task_queue=queue
        )
        await _wait_for(handle, "awaiting:start")
        # A person approves, and the approval is recorded with their name before the signal.
        grant_approval(dsn, campaign_id, "start", DPO)
        await handle.signal(CampaignWorkflow.approve, "start")
        await _approve_sampling_if_asked(dsn, campaign_id, handle)
        return dict(await handle.result())


async def _approve_sampling_if_asked(dsn: str, campaign_id: str, handle: Any) -> None:
    """Sampling always takes two different people (SEC-009): both approve when it is asked."""
    for _ in range(120):
        status = (await handle.query(CampaignWorkflow.progress)).get("status")
        if status == "awaiting:sampling":
            grant_approval(dsn, campaign_id, "sampling", DPO, needed=2)
            grant_approval(dsn, campaign_id, "sampling", SECOND_DPO, needed=2)
            await handle.signal(CampaignWorkflow.approve, "sampling")
            return
        if status in ("running", "sealed"):
            return
        await asyncio.sleep(1)


async def _wait_for(handle: Any, state: str, tries: int = 120) -> None:
    for _ in range(tries):
        progress = await handle.query(CampaignWorkflow.progress)
        if progress.get("status") == state:
            return
        await asyncio.sleep(1)
    raise AssertionError(f"the campaign never reached {state}")


def _verdicts(dsn: str, campaign_id: str, systems: dict[str, str]) -> set[ExpectedVerdict]:
    """The worst result per challenge and system, as the ground truth states it."""
    by_id = {value: key for key, value in systems.items()}
    results: dict[tuple[str, str], list[str]] = defaultdict(list)
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT v.challenge_id, u.unit->>'system_id', v.result "
            "FROM argos.verdicts v JOIN argos.campaign_units u "
            "ON u.campaign_id = v.campaign_id AND u.unit_id = v.unit_id "
            "WHERE v.campaign_id = %s",
            (campaign_id,),
        ).fetchall()
    for challenge_id, system_id, result in rows:
        results[(str(challenge_id), by_id[str(system_id)])].append(str(result))
    return {
        ExpectedVerdict(challenge_id, system, worst_of(seen), "")
        for (challenge_id, system), seen in results.items()
    }


@pytest.fixture(scope="module")
def campaign(phase5_db: str, demo: dict[str, str]) -> dict[str, Any]:
    campaign_id = create_campaign(phase5_db, "Campaña de la prueba de fase", {}, MANAGER)
    summary = asyncio.run(_run(phase5_db, campaign_id))
    return {"id": campaign_id, "summary": summary}


def test_the_campaign_reproduces_the_ground_truth(
    phase5_db: str, demo: dict[str, str], campaign: dict[str, Any]
) -> None:
    """Criterion 3: the verdicts are the ones written by hand before the engine existed."""
    found = _verdicts(phase5_db, campaign["id"], demo)
    expected = {ExpectedVerdict(v.challenge_id, v.system, v.result, "") for v in TRUTH.verdicts}
    assert (sorted(expected - found), sorted(found - expected)) == ([], [])


def test_the_findings_are_the_planted_ones(
    phase5_db: str, demo: dict[str, str], campaign: dict[str, Any]
) -> None:
    by_id = {value: key for key, value in demo.items()}
    with psycopg.connect(phase5_db) as conn:
        rows = conn.execute(
            "SELECT DISTINCT challenge_id, system_id::text, obligation "
            "FROM argos.findings WHERE campaign_id = %s",
            (campaign["id"],),
        ).fetchall()
    # The finding keeps the obligation as an IRI; the ground truth names it by its id.
    found = {
        (str(row[0]), by_id[str(row[1])], str(row[2]).removeprefix(str(NORMS))) for row in rows
    }
    expected = {(f.challenge_id, f.system, f.obligation) for f in TRUTH.findings}
    assert (sorted(expected - found), sorted(found - expected)) == ([], [])


def test_what_the_demonstration_cannot_verify_is_said_out_loud(
    phase5_db: str, demo: dict[str, str], campaign: dict[str, Any]
) -> None:
    """An obligation with no evidence source is reported, never passed off as verified."""
    by_id = {value: key for key, value in demo.items()}
    with psycopg.connect(phase5_db) as conn:
        row = conn.execute(
            "SELECT payload FROM argos.approval_requests WHERE campaign_id = %s AND gate = 'start'",
            (campaign["id"],),
        ).fetchone()
    assert row is not None
    unverifiable = row[0]["unverifiable"]
    found = {(str(row["challenge_id"]), by_id[str(row["system_id"])]) for row in unverifiable}
    expected = {(u.challenge_id, u.system) for u in TRUTH.unverifiable}
    assert expected <= found
    assert all(str(row["reason"]).strip() for row in unverifiable)


def test_the_aggregate_per_system_is_the_expected_one(
    phase5_db: str, demo: dict[str, str], campaign: dict[str, Any]
) -> None:
    found = _verdicts(phase5_db, campaign["id"], demo)
    for system, expected in TRUTH.aggregate.items():
        results = [v.result for v in found if v.system == system]
        assert worst_of(results) == expected, system


def test_the_campaign_covers_more_than_fifteen_challenges_of_two_norms(
    phase5_db: str, campaign: dict[str, Any]
) -> None:
    """Criterion 1: the library that ships, not a handful of challenges written for the test."""
    with psycopg.connect(phase5_db) as conn:
        rows = conn.execute(
            "SELECT DISTINCT challenge_id, obligation FROM argos.verdicts WHERE campaign_id = %s",
            (campaign["id"],),
        ).fetchall()
    assert len({row[0] for row in rows}) >= 15
    assert {str(row[1]).split("-")[1] for row in rows} >= {"RGPD", "AIACT"}


def test_the_start_gate_was_approved_by_a_person(phase5_db: str, campaign: dict[str, Any]) -> None:
    """Criterion 2: nothing ran before a person approved the campaign."""
    with psycopg.connect(phase5_db) as conn:
        rows = conn.execute(
            "SELECT gate, approved_by FROM argos.approvals WHERE campaign_id = %s",
            (campaign["id"],),
        ).fetchall()
    approvals: dict[str, set[str]] = defaultdict(set)
    for gate, approved_by in rows:
        approvals[str(gate)].add(str(approved_by))
    assert approvals["start"] == {DPO}


def test_the_sampling_gate_needs_two_different_people(phase5_db: str) -> None:
    """Criterion 2, double control. No challenge of the shipped library samples, so the gate is
    not reached in this campaign; the rule itself is exercised here on its own campaign."""
    other = create_campaign(phase5_db, "Campaña con muestreo", {}, MANAGER)
    request_approval(phase5_db, other, "sampling", {"units": 1})
    granted, opened = grant_approval(phase5_db, other, "sampling", DPO, needed=2)
    assert (granted, opened) == (1, False)
    with pytest.raises(CampaignStateError):
        grant_approval(phase5_db, other, "sampling", DPO, needed=2)
    assert grant_approval(phase5_db, other, "sampling", SECOND_DPO, needed=2) == (2, True)


def test_the_same_snapshot_gives_the_same_verdict_hashes(
    phase5_db: str, demo: dict[str, str], campaign: dict[str, Any]
) -> None:
    """Criterion 4: determinism, unit by unit, over a second campaign on the same snapshot."""
    again = create_campaign(phase5_db, "Reejecución sobre la misma instantánea", {}, MANAGER)
    asyncio.run(_run(phase5_db, again))
    with psycopg.connect(phase5_db) as conn:
        rows = conn.execute(
            "SELECT campaign_id::text, challenge_id, node_key, "
            "(verdict - 'unit_id')::text FROM argos.verdicts WHERE campaign_id = ANY(%s)",
            ([campaign["id"], again],),
        ).fetchall()
    first = {(r[1], r[2]): r[3] for r in rows if str(r[0]) == campaign["id"]}
    second = {(r[1], r[2]): r[3] for r in rows if str(r[0]) == again}
    assert first and set(first) == set(second)
    # The unit id carries the campaign, so it is left out: what must not move is the evidence.
    assert [key for key in first if first[key] != second[key]] == []


def test_the_seal_verifies_and_breaks_when_a_verdict_is_touched(
    phase5_db: str, campaign: dict[str, Any]
) -> None:
    """Criteria 5: the seal is what makes the campaign evidence, and it is not decorative."""
    record = campaign_record(phase5_db, campaign["id"])
    assert record["status"] == "sealed" and record["seal"]
    assert verify_seal(phase5_db, campaign["id"])
    with psycopg.connect(phase5_db) as conn:
        conn.execute("ALTER TABLE argos.verdicts DISABLE TRIGGER verdicts_write_once")
        conn.execute(
            "UPDATE argos.verdicts SET verdict_hash = %s WHERE campaign_id = %s "
            "AND verdict_hash = (SELECT min(verdict_hash) FROM argos.verdicts "
            "WHERE campaign_id = %s)",
            ("0" * 64, campaign["id"], campaign["id"]),
        )
        conn.execute("ALTER TABLE argos.verdicts ENABLE TRIGGER verdicts_write_once")
    assert not verify_seal(phase5_db, campaign["id"])


async def _approve_remediation(dsn: str, origin: str) -> None:
    """The DPOs approve the gates the remediation campaign asks for: two people for sampling."""
    while True:
        with psycopg.connect(dsn) as conn:
            rows = conn.execute(
                "SELECT r.campaign_id::text, r.gate FROM argos.approval_requests r "
                "JOIN argos.campaigns c ON c.id = r.campaign_id "
                "WHERE c.scope->>'campaign_id' = %s",
                (origin,),
            ).fetchall()
        for remediation_id, gate in rows:
            approvers = (DPO, SECOND_DPO) if gate == "sampling" else (DPO,)
            for approver in approvers:
                with contextlib.suppress(CampaignStateError):
                    grant_approval(dsn, remediation_id, gate, approver, needed=len(approvers))
        await asyncio.sleep(0.5)


async def _remediate(dsn: str, campaign_id: str) -> dict[str, Any]:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    activities = ChallengeActivities(dsn, secret_store())
    queue = f"argos-phase5-remediation-{uuid.uuid4().hex[:8]}"
    approver = asyncio.create_task(_approve_remediation(dsn, campaign_id))
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
                    id=f"remediation-{campaign_id}-{uuid.uuid4().hex[:6]}",
                    task_queue=queue,
                )
            )
    finally:
        approver.cancel()


def _finding(dsn: str, campaign_id: str, challenge_id: str, system_id: str) -> str:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT id::text FROM argos.findings "
            "WHERE campaign_id = %s AND challenge_id = %s AND system_id = %s",
            (campaign_id, challenge_id, system_id),
        ).fetchone()
    assert row is not None, f"no finding for {challenge_id} on {system_id}"
    return str(row[0])


def _status(dsn: str, finding_id: str) -> str:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT status FROM argos.findings WHERE id = %s", (finding_id,)
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_what_the_client_fixed_closes_and_what_it_did_not_reopens(
    phase5_db: str, demo: dict[str, str], campaign: dict[str, Any]
) -> None:
    """Criterion 6: the remediation is verified with the same challenge that found the problem."""
    mariadb = demo["dev-source-mariadb"]
    fixed = _finding(phase5_db, campaign["id"], "dsr-erasure-effective", mariadb)
    not_fixed = _finding(phase5_db, campaign["id"], "sec-encryption-in-transit", mariadb)
    for finding_id in (fixed, not_fixed):
        transition(phase5_db, finding_id, "in_remediation", DPO)
        transition(phase5_db, finding_id, "pending_verification", DPO)

    _the_client_erases_the_subject_from_the_replica()
    summary = await_remediation(phase5_db, campaign["id"])

    assert summary["verified"] == 2
    assert (summary["closed"], summary["reopened"]) == (1, 1)
    assert _status(phase5_db, fixed) == "closed_compliant"
    assert _status(phase5_db, not_fixed) == "reopened"


def await_remediation(dsn: str, campaign_id: str) -> dict[str, Any]:
    return asyncio.run(_remediate(dsn, campaign_id))


def _the_client_erases_the_subject_from_the_replica() -> None:
    """The client honours the erasure it had missed; ARGOS never writes in a client system."""
    _demo_client().erase_from_replica(generate_subjects(SEED, 1)[0])
