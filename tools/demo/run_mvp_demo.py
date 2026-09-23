"""The MVP demonstration, end to end, on the development environment (Plan Director, Annex F).

    uv run python tools/demo/run_mvp_demo.py [--out .scratch/demo] [--drop]

Needs `make dev`. Every step prints what it shows and leaves its output in the
output folder: inventory, the write that fails, the campaign with its planted
findings and the synthetic subject, the dossier (JSON and PDF), the credential,
the verification bundle and the public verifier's report, and the report of a
bundle with one corrupted byte. The demonstration works in a database of its
own, so the development one is not touched, and it reverts the synthetic
subject in the sources before it ends.

The console arrives with Phase 08; until then this script is the demonstration.
The summary drafted by the local model needs its weights (F06-05) and is not
part of this run.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import copy
import importlib.util
import json
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))  # the demonstration scenario is the test one: same truth

import psycopg  # noqa: E402
from fixtures.campaign_ground_truth import load_campaign_truth  # noqa: E402
from fixtures.demo_review import apply_demo_review  # noqa: E402
from integration.conftest import ADMIN_DSN, MIGRATIONS_DIR  # noqa: E402
from integration.inventory_helpers import (  # noqa: E402
    probe_runner,
    scan_and_ingest,
    secret_store,
)
from integration.sources import open_source_connector  # noqa: E402
from psycopg import sql  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from temporalio.client import Client  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from argos_challenges.activities import ChallengeActivities  # noqa: E402
from argos_challenges.store import create_campaign, grant_approval  # noqa: E402
from argos_challenges.synthetic import (  # noqa: E402
    authorize_injection,
    confirm_exercise,
    confirm_injection,
    generate_subjects,
    register_subjects,
)
from argos_challenges.workflows import CampaignWorkflow, SystemRun  # noqa: E402
from argos_common.config import get_config  # noqa: E402
from argos_common.migrations import apply_migrations  # noqa: E402
from argos_connector.testing import assert_sql_writes_rejected  # noqa: E402
from argos_evidence.service import build_activities  # noqa: E402
from argos_evidence.settings import EvidenceSettings  # noqa: E402
from argos_evidence.workflow import EvidenceWorkflow  # noqa: E402
from argos_inventory.ai_discovery.detect import discover_ai  # noqa: E402
from argos_inventory.catalog.treatments import import_treatments  # noqa: E402
from argos_inventory.classify.deterministic import classify_new_columns  # noqa: E402
from argos_inventory.graph.store import GraphStore  # noqa: E402
from argos_ontology.store import store_version  # noqa: E402
from argos_ontology.traceability import library_graph  # noqa: E402
from argos_sql.postgres import PostgresConnector  # noqa: E402
from argos_verifier.checks import verify_bundle  # noqa: E402

TREATMENTS = REPO / "deploy" / "dev" / "ropa" / "treatments.csv"
ONTOLOGY_VERSION = "1.0.0"
IN_FORCE = date(2024, 8, 1)
MANAGER = "user:campaign-manager"
DPO = "user:dpo"
SEED = "demo-campaign"
STAR_CHALLENGE = "dsr-erasure-effective"
DEV_VAULT_TOKEN = "root"  # noqa: S105 - development Vault started with -dev-root-token-id=root
# The same values the evidence containers run with (deploy/dev/compose.yaml), seen from the host.
DEV_EVIDENCE = {
    "ISSUER_DID": "did:web:127.0.0.1%3A8008",
    "STATUS_BASE_URL": "http://127.0.0.1:8008/status",
    "CREDENTIAL_BASE_URL": "http://127.0.0.1:8008/credentials",
    "VERIFIER_URL": "http://127.0.0.1:8007/verify",
    "RETENTION_DAYS": 1,
    "S3_ENDPOINT": "http://127.0.0.1:7075",
    "S3_ACCESS_KEY": "dev-only-evidence",
    "S3_SECRET_KEY": "dev-only-evidence-secret",
    "TSA_URL": "http://127.0.0.1:3180",
    "TSA_ROOTS_URL": "http://127.0.0.1:3180/ca.pem",
}


def _say(step: str, text: str) -> None:
    print(f"\n== {step} ==\n{text}")


def _write(out: Path, name: str, data: Any) -> None:
    target = out / name
    if isinstance(data, bytes):
        target.write_bytes(data)
    else:
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _demo_client() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "demo_client_actions", REPO / "tools" / "demo_client_actions.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("tools/demo_client_actions.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _new_database() -> str:
    name = f"argos_demo_{datetime.now():%Y%m%d_%H%M%S}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = f"{ADMIN_DSN.rsplit('/', 1)[0]}/{name}"
    apply_migrations(dsn, MIGRATIONS_DIR)
    return dsn


def _drop_database(dsn: str) -> None:
    name = dsn.rsplit("/", 1)[1]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


def _inventory(dsn: str, systems: list[str]) -> dict[str, str]:
    store = GraphStore(dsn)
    ids = {}
    for name in systems:
        ids[name] = scan_and_ingest(dsn, name)
        classify_new_columns(store, probe_runner(dsn), ids[name])
    discover_ai(store)
    apply_demo_review(store, dsn, ids)
    import_treatments(store, dsn, TREATMENTS.read_bytes(), DPO)
    store_version(dsn, ONTOLOGY_VERSION, IN_FORCE, library_graph(), "e" * 64, {}, b"demo")
    return ids


def _write_attempt(dsn: str) -> str:
    connector = open_source_connector("dev-source-postgres", PostgresConnector, dsn)
    try:
        assert_sql_writes_rejected(connector, "clinic.patients")
    finally:
        connector.close()
    return "rejected"


def _inject_subject(dsn: str, systems: dict[str, str]) -> None:
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


async def _campaign(dsn: str, campaign_id: str) -> dict[str, Any]:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    activities = ChallengeActivities(dsn, secret_store())
    queue = f"argos-demo-{uuid.uuid4().hex[:8]}"
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
        for _ in range(120):
            if (await handle.query(CampaignWorkflow.progress)).get("status") == "awaiting:start":
                break
            await asyncio.sleep(1)
        # A person approves, and the approval is recorded with their name before the signal.
        grant_approval(dsn, campaign_id, "start", DPO)
        await handle.signal(CampaignWorkflow.approve, "start")
        return dict(await handle.result())


async def _evidence(activities: Any, campaign_id: str) -> dict[str, Any]:
    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    queue = f"argos-demo-evidence-{uuid.uuid4().hex[:8]}"
    async with Worker(
        client, task_queue=queue, workflows=[EvidenceWorkflow], activities=activities.all()
    ):
        result: dict[str, Any] = await client.execute_workflow(
            EvidenceWorkflow.run,
            args=[campaign_id, 3, 2],
            id=f"evidence-demo-{campaign_id}",
            task_queue=queue,
        )
    return result


WORST_FIRST = ("non_compliant", "inconclusive", "not_demonstrated", "compliant")


def _worst(results: list[str] | None) -> str | None:
    return next((r for r in WORST_FIRST if r in (results or [])), None)


def _failed(report: Any) -> list[str]:
    return [c.name for c in report.checks if c.status == "failed"]


def run_demo(out: Path, keep_database: bool = True) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    truth = load_campaign_truth()
    dsn = _new_database()
    subject = generate_subjects(SEED, 1)[0]
    _demo_client().revert(subject)  # start from the sources the ground truth describes
    summary: dict[str, Any] = {"database": dsn.rsplit("/", 1)[1]}
    try:
        systems = _inventory(dsn, list(truth.systems))
        summary["inventory"] = {"systems": len(systems), "ids": systems}
        _write(out, "inventory.json", summary["inventory"])
        _say("ARGOS ve", f"{len(systems)} sistemas inventariados: {', '.join(systems)}")

        summary["write_attempt"] = _write_attempt(dsn)
        _say("Solo lectura", "El arnés intenta escribir en la fuente clínica: rechazado.")

        _inject_subject(dsn, systems)
        campaign_id = create_campaign(dsn, "Demostración del MVP", {}, MANAGER)
        campaign = asyncio.run(_campaign(dsn, campaign_id))
        with psycopg.connect(dsn) as conn:
            # A challenge runs one unit per asset: what the audience sees is the worst result per
            # challenge and system, as the campaign ground truth states it.
            star = conn.execute(
                "SELECT array_agg(DISTINCT result) FROM argos.verdicts WHERE campaign_id = %s"
                " AND challenge_id = %s AND system_id = %s",
                (campaign_id, STAR_CHALLENGE, systems["dev-source-mariadb"]),
            ).fetchone()
            obligations = [
                str(r[0]).rsplit("/", 1)[-1]
                for r in conn.execute(
                    "SELECT DISTINCT unit->>'obligation' FROM argos.campaign_units"
                    " WHERE campaign_id = %s ORDER BY 1",
                    (campaign_id,),
                ).fetchall()
            ]
            findings = conn.execute(
                "SELECT DISTINCT f.challenge_id, s.name, f.severity FROM argos.findings f"
                " JOIN argos.systems s ON s.id = f.system_id WHERE f.campaign_id = %s"
                " ORDER BY 1, 2",
                (campaign_id,),
            ).fetchall()
        summary["campaign"] = {
            "id": campaign_id,
            "status": campaign["status"],
            "obligations": obligations,
            "findings": [list(f) for f in findings],
        }
        summary["star_challenge"] = {
            "challenge": STAR_CHALLENGE,
            "result": _worst(star[0] if star else None),
        }
        _write(out, "campaign.json", summary["campaign"])
        _say(
            "ARGOS sabe qué exigir",
            f"{len(obligations)} obligaciones verificables aplican a esta instantánea: "
            + ", ".join(obligations),
        )
        _say(
            "ARGOS reta",
            f"Campaña sellada con {len(findings)} hallazgos. Reto estrella {STAR_CHALLENGE} en la"
            f" réplica de facturación: {summary['star_challenge']['result']}.",
        )

        # The development Vault's root token, as the evidence containers use it (compose).
        config = get_config().model_copy(
            update={"DATABASE_URL": dsn, "VAULT_TOKEN": SecretStr(DEV_VAULT_TOKEN)}
        )
        activities = build_activities(config, EvidenceSettings(**DEV_EVIDENCE))
        evidence = asyncio.run(_evidence(activities, campaign_id))
        bundle = activities.bundle(evidence["dossier"])
        dossier = base64.b64decode(bundle["dossier"])
        with psycopg.connect(dsn) as conn:
            pdf_key, pdf_version = conn.execute(
                "SELECT pdf_key, pdf_version_id FROM argos.dossiers WHERE sha256 = %s",
                (evidence["dossier"],),
            ).fetchone() or ("", "")
        _write(out, "dossier.json", dossier)
        _write(out, "dossier.pdf", activities.stored(pdf_key, pdf_version))
        _write(out, "credential.json", bundle["credential"])
        _write(out, "bundle.json", bundle)
        _say(
            "ARGOS prueba", f"Expediente {evidence['dossier']} con sello {evidence['time_stamp']}."
        )

        report = verify_bundle(bundle)
        summary["verification"] = report.as_dict()
        _write(out, "report.json", report.as_dict())
        _say("Comprobador público", "Paquete íntegro: " + ("verificado" if report.ok else "NO"))

        tampered = copy.deepcopy(bundle)
        raw = bytearray(base64.b64decode(tampered["artifacts"][0]["artifact"]))
        raw[len(raw) // 2] ^= 0x01
        tampered["artifacts"][0]["artifact"] = base64.b64encode(bytes(raw)).decode("ascii")
        broken = verify_bundle(tampered)
        summary["tampered"] = {"ok": broken.ok, "failed": _failed(broken)}
        _write(out, "tampered-report.json", broken.as_dict())
        _say("Un byte corrupto", f"Comprobaciones que fallan: {', '.join(_failed(broken))}")
        return summary
    finally:
        _demo_client().revert(subject)
        if not keep_database:
            _drop_database(dsn)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO / ".scratch" / "demo")
    parser.add_argument("--drop", action="store_true", help="drop the demonstration database")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    summary = run_demo(args.out, keep_database=not args.drop)
    _write(args.out, "summary.json", summary)
    return 0 if summary["verification"]["ok"] and not summary["tampered"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
