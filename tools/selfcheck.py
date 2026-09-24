"""ARG-100 · ARGOS verifies ARGOS: the self-* campaign and the release gate (F10-01).

    uv run python tools/selfcheck.py [--out dist] [--dev-setup] [--publish-content]

A release is not declared verified: it arrives with the dossier of a campaign that ARGOS ran
against itself, with the same engine, library and evidence chain as any other campaign.

1. The appliance is a system of its own inventory, `argos-appliance`, read by the SQL connector
   with a login of the role `svc_selfcheck`, which only reads the facts of `argos_facts.facts`.
2. The campaign measures only that system; before its start is approved, the plan is checked to
   hold only self-* challenges, the trap included.
3. After the seal, the evidence chain writes the dossier. The gate reads that dossier: no critical
   or high finding, and the finding of the trap `self-099` present. Without it the campaign did not
   evaluate, and the release is blocked like it would be by a serious finding.

The dossier and its PDF are left in `<out>/selfcheck-<version>/`. It is the local gate of every
release (decision DP-16); the CI job waits for a runner with the whole environment.

`--dev-setup` prepares the development environment: the login of `svc_selfcheck` with its
development password, the system in `argos.systems`, its credential in Vault and its System node.
On an appliance the installer does that (ARG-096). `--publish-content` loads the library on disk
as a new signed content bundle when the one in force is not it: in development the library changes
between releases, and a campaign only runs signed content (SEC-011). The start gate is approved by
the bench account of the release (`user:release-approver`), a person other than the one who creates
the campaign: separation of duties holds for the self-check too.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import secrets
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
TRAP = "self-099"
SELF_PREFIX = "self-"
SERIOUS = ("critical", "high")
DOSSIER_SCHEMA = "argos/dossier/1"

APPLIANCE_ID = "01920000-0000-7000-8000-00000000f001"
APPLIANCE_NAME = "argos-appliance"
APPLIANCE_CONNECTOR = "argos_sql.postgres:PostgresConnector"
SELFCHECK_LOGIN = "argos_selfcheck"
DEV_SELFCHECK_PASSWORD = "dev-only-selfcheck"  # noqa: S105 - development login, never an appliance
MANAGER = "user:release-manager"
APPROVER = "user:release-approver"
PREPARE_WAIT_SECONDS = 600
DEV_VAULT = "http://127.0.0.1:8200"
DEV_VAULT_TOKEN = "root"  # noqa: S105 - development Vault started with -dev-root-token-id=root
DEV_ADMIN_DSN = "postgresql://argos@127.0.0.1:55432/argos"
DEV_CA = REPO / "deploy" / "dev" / "secrets" / "tls-host" / "ca.crt"
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


class SelfcheckError(RuntimeError):
    """The self-check could not run to a sealed campaign; the release is blocked all the same."""


# ---------- the gate: pure, over the dossier ----------


def gate(dossier: Mapping[str, Any]) -> list[str]:
    """The reasons that block the release; an empty list lets it through."""
    reasons: list[str] = []
    if dossier.get("schema") != DOSSIER_SCHEMA:
        reasons.append(f"the document is not a dossier {DOSSIER_SCHEMA}: {dossier.get('schema')!r}")
    campaign = dossier.get("campaign") or {}
    if campaign.get("status") != "sealed":
        reasons.append(f"the campaign is not sealed: {campaign.get('status')!r}")
    if int((dossier.get("results") or {}).get("units") or 0) == 0:
        reasons.append("the campaign evaluated no unit")
    findings = list(dossier.get("findings") or [])
    for finding in findings:
        challenge = str(finding.get("challenge_id"))
        severity = str(finding.get("severity"))
        if not challenge.startswith(SELF_PREFIX):
            reasons.append(f"finding of {challenge}, outside the self-* family: wrong scope")
        if severity in SERIOUS:
            reasons.append(f"{severity} finding of {challenge} ({finding.get('obligation')})")
    if not any(str(f.get("challenge_id")) == TRAP for f in findings):
        reasons.append(f"no finding of the trap {TRAP}: the campaign did not really evaluate")
    return reasons


def self_challenges(library_dir: Path) -> dict[str, dict[str, Any]]:
    """The self-* challenges of the library, by id."""
    found: dict[str, dict[str, Any]] = {}
    for path in sorted((library_dir / "challenges" / "self").glob("*.yaml")):
        challenge = yaml.safe_load(path.read_text(encoding="utf-8"))
        found[str(challenge["id"])] = challenge
    return found


# ---------- the environment: the appliance as a system of its own inventory ----------


def appliance_url(password: str, database: str = "argos", ca: Path = DEV_CA) -> str:
    return (
        f"postgresql+psycopg://{SELFCHECK_LOGIN}:{password}@127.0.0.1:55432/{database}"
        f"?sslmode=verify-full&sslrootcert={ca.as_posix()}"
    )


def dev_setup(
    admin_dsn: str, vault_url: str, vault_token: str, system_id: str = APPLIANCE_ID
) -> None:
    """Development only: the login, the system, its credential and its System node.

    The system reads the database of `admin_dsn`: the development one, or a disposable one in the
    tests, registered under another `system_id` so the development credential is not touched.
    """
    import hvac
    import psycopg
    from psycopg import sql

    from argos_inventory.graph.store import GraphStore
    from argos_inventory.ingest.handlers import SYSTEM_UPSERT, load_system_meta
    from argos_inventory.ingest.parameters import system_parameters

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (SELFCHECK_LOGIN,)
        ).fetchone()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(
            sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
                sql.SQL(verb), sql.Identifier(SELFCHECK_LOGIN), sql.Literal(DEV_SELFCHECK_PASSWORD)
            )
        )
        conn.execute(sql.SQL("GRANT svc_selfcheck TO {}").format(sql.Identifier(SELFCHECK_LOGIN)))
        connection = {
            "secret": f"connectors/{system_id}",
            "connector": APPLIANCE_CONNECTOR,
            "config": {"statement_timeout_ms": 5000},
        }
        conn.execute(
            "INSERT INTO argos.systems (id, name, kind, environment, connection)"
            " VALUES (%s, %s, 'rdbms', 'development', %s::jsonb)"
            " ON CONFLICT (id) DO UPDATE SET connection = EXCLUDED.connection",
            (system_id, APPLIANCE_NAME, json.dumps(connection)),
        )
    vault = hvac.Client(url=vault_url, token=vault_token)
    path = f"connectors/{system_id}"
    try:
        current = vault.secrets.kv.v2.read_secret_version(
            path=path, mount_point="argos", raise_on_deleted_version=True
        )["data"]["data"]
    except hvac.exceptions.InvalidPath:
        current = {}
    vault.secrets.kv.v2.create_or_update_secret(
        path=path,
        mount_point="argos",
        secret={
            "url": appliance_url(DEV_SELFCHECK_PASSWORD, admin_dsn.rsplit("/", 1)[1].split("?")[0]),
            "hash_key": current.get("hash_key") or secrets.token_hex(32),
        },
    )
    # The appliance enters its inventory as a System node; its tables are not explored: ARGOS is
    # not a source of personal data of the client, and its facts are all the self-check reads.
    store = GraphStore(admin_dsn)
    meta = load_system_meta(admin_dsn, system_id)
    with store.connection() as conn:
        store.execute(SYSTEM_UPSERT, system_parameters(meta, datetime.now(UTC).isoformat()), conn)


def _next_version(newest: str | None) -> str:
    if newest is None:
        return "1.0.0"
    major, minor, patch = (int(part) for part in newest.split("."))
    return f"{major}.{minor}.{patch + 1}"


def content_in_force(dsn: str, publish: bool, vault_url: str, vault_token: str) -> str:
    """The signed content in force, when it is the library on disk; else published, if allowed."""
    import psycopg

    from argos_common.errors import IntegrityError
    from argos_common.release import VaultTransitSigner
    from argos_ontology.bundle import publish_library, verify_on_disk
    from argos_ontology.store import version_in_force
    from argos_ontology.vocabulary import LIBRARY_DIR

    try:
        version = version_in_force(dsn)
        verify_on_disk(dsn, version, LIBRARY_DIR)
        return version
    except (LookupError, IntegrityError) as exc:
        if not publish:
            raise SelfcheckError(
                f"the library on disk is not the signed content in force ({exc});"
                " load the release bundle, or use --publish-content in development"
            ) from exc
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT version FROM argos.ontology_bundles").fetchall()
    loaded = [str(r[0]) for r in rows if str(r[0]).count(".") == 2]
    newest = max(loaded, key=lambda v: tuple(int(p) for p in v.split("."))) if loaded else None
    record = publish_library(
        dsn,
        LIBRARY_DIR,
        _next_version(newest),
        datetime.now(UTC).date(),
        VaultTransitSigner(vault_url, vault_token, key="argos-content"),
    )
    return record.version


# ---------- the campaign and its evidence ----------


def _plan_challenges(dsn: str, campaign_id: str) -> set[str]:
    import psycopg

    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT DISTINCT unit->>'challenge_id' FROM argos.campaign_units"
            " WHERE campaign_id = %s",
            (campaign_id,),
        ).fetchall()
    return {str(row[0]) for row in rows}


async def _campaign(dsn: str, campaign_id: str) -> dict[str, Any]:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from argos_challenges.activities import ChallengeActivities
    from argos_challenges.store import grant_approval
    from argos_challenges.workflows import CampaignWorkflow, SystemRun
    from argos_common.config import get_config
    from argos_common.secret_stores import VaultSecretStore

    config = get_config()
    client = await Client.connect(config.TEMPORAL_ADDRESS, namespace="default")
    token = os.environ.get("ARGOS_SELFCHECK_VAULT_TOKEN", DEV_VAULT_TOKEN)
    activities = ChallengeActivities(
        dsn, VaultSecretStore(os.environ.get("ARGOS_SELFCHECK_VAULT", DEV_VAULT), token)
    )
    queue = f"argos-selfcheck-{uuid.uuid4().hex[:8]}"
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
            activities.check_reversions,
        ],
    ):
        handle = await client.start_workflow(
            CampaignWorkflow.run, campaign_id, id=f"selfcheck-{campaign_id}", task_queue=queue
        )
        for _ in range(PREPARE_WAIT_SECONDS):
            if (await handle.query(CampaignWorkflow.progress)).get("status") == "awaiting:start":
                break
            await asyncio.sleep(1)
        else:
            raise SelfcheckError(
                f"the campaign did not ask for its start in {PREPARE_WAIT_SECONDS} s"
            )
        planned = await asyncio.to_thread(_plan_challenges, dsn, campaign_id)
        outside = sorted(c for c in planned if not c.startswith(SELF_PREFIX))
        if outside or TRAP not in planned:
            await handle.cancel()
            raise SelfcheckError(
                f"the plan is not the self-check: outside the family {outside},"
                f" trap planned: {TRAP in planned}"
            )
        # The start is approved by a person other than the one who created the campaign.
        grant_approval(dsn, campaign_id, "start", APPROVER)
        await handle.signal(CampaignWorkflow.approve, "start")
        return dict(await handle.result())


async def _evidence(activities: Any, campaign_id: str) -> dict[str, Any]:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from argos_common.config import get_config
    from argos_evidence.workflow import EvidenceWorkflow

    client = await Client.connect(get_config().TEMPORAL_ADDRESS, namespace="default")
    queue = f"argos-selfcheck-evidence-{uuid.uuid4().hex[:8]}"
    async with Worker(
        client, task_queue=queue, workflows=[EvidenceWorkflow], activities=activities.all()
    ):
        result: dict[str, Any] = await client.execute_workflow(
            EvidenceWorkflow.run,
            args=[campaign_id, 3, 2],
            id=f"evidence-selfcheck-{campaign_id}",
            task_queue=queue,
        )
    return result


def run_campaign(dsn: str, version: str, system_id: str = APPLIANCE_ID) -> str:
    """Create the self-* campaign of the appliance and run it until it seals; its id."""
    from argos_challenges.store import create_campaign

    campaign_id = create_campaign(
        dsn, f"Autoverificación de ARGOS {version}", {"system_ids": [system_id]}, MANAGER
    )
    asyncio.run(_campaign(dsn, campaign_id))
    return campaign_id


def write_dossier(
    dsn: str, campaign_id: str, out: Path, version: str
) -> tuple[dict[str, Any], Path]:
    """The evidence chain of the sealed campaign and the files of the release; the dossier parsed.

    The chain refuses to anchor a broken journal: then there is no dossier, and no release.
    """
    import psycopg
    from pydantic import SecretStr

    from argos_common.config import get_config
    from argos_evidence.service import build_activities
    from argos_evidence.settings import EvidenceSettings

    config = get_config().model_copy(
        update={
            "DATABASE_URL": dsn,
            "VAULT_TOKEN": SecretStr(
                os.environ.get("ARGOS_SELFCHECK_VAULT_TOKEN", DEV_VAULT_TOKEN)
            ),
        }
    )
    activities = build_activities(config, EvidenceSettings(**DEV_EVIDENCE))
    try:
        evidence = asyncio.run(_evidence(activities, campaign_id))
    except Exception as exc:  # the workflow failure carries the cause of the evidence chain
        cause: BaseException = exc
        while cause.__cause__ is not None:  # workflow -> activity -> what the chain refused
            cause = cause.__cause__
        raise SelfcheckError(f"no dossier for campaign {campaign_id}: {cause}") from exc
    bundle = activities.bundle(evidence["dossier"])
    raw = base64.b64decode(bundle["dossier"])
    with psycopg.connect(dsn) as conn:
        pdf_key, pdf_version = conn.execute(
            "SELECT pdf_key, pdf_version_id FROM argos.dossiers WHERE sha256 = %s",
            (evidence["dossier"],),
        ).fetchone() or ("", "")
    target = out / f"selfcheck-{version}"
    target.mkdir(parents=True, exist_ok=True)
    (target / "dossier.json").write_bytes(raw)
    (target / "dossier.pdf").write_bytes(activities.stored(pdf_key, pdf_version))
    (target / "bundle.json").write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return dict(json.loads(raw)), target


def run(
    dsn: str, out: Path, version: str, system_id: str = APPLIANCE_ID
) -> tuple[dict[str, Any], Path]:
    """The campaign, its dossier and the files of the release; the dossier is returned parsed."""
    return write_dossier(dsn, run_campaign(dsn, version, system_id), out, version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO / "dist")
    parser.add_argument("--dev-setup", action="store_true", help="prepare the development system")
    parser.add_argument(
        "--publish-content", action="store_true", help="load the library as signed content"
    )
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    dsn = os.environ.get("ARGOS_SELFCHECK_DSN", DEV_ADMIN_DSN)
    vault = os.environ.get("ARGOS_SELFCHECK_VAULT", DEV_VAULT)
    token = os.environ.get("ARGOS_SELFCHECK_VAULT_TOKEN", DEV_VAULT_TOKEN)
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    try:
        if args.dev_setup:
            dev_setup(dsn, vault, token)
        content = content_in_force(dsn, args.publish_content, vault, token)
        print(f"content in force: {content}")
        dossier, folder = run(dsn, args.out, version)
    except SelfcheckError as exc:
        print(f"selfcheck: BLOCKED: {exc}", file=sys.stderr)
        return 1
    reasons = gate(dossier)
    for finding in dossier.get("findings", []):
        print(f"  {finding['severity']:8} {finding['challenge_id']} ({finding['obligation']})")
    if reasons:
        print(f"selfcheck: BLOCKED ({folder}):", file=sys.stderr)
        for reason in reasons:
            print(f"  - {reason}", file=sys.stderr)
        return 1
    print(f"selfcheck: passed on {date.today().isoformat()}; dossier in {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
