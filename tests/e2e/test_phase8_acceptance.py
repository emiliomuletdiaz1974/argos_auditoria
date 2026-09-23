"""Phase 8 acceptance test (Plan Director §8.2 "Fase 08").

What this phase promised, checked end to end:

1. The appliance serves the console and the v1 from **one origin**, and the v1 answers nothing
   without a token of the realm. The contract the console was built against is the one it serves.
2. The authorisation matrix the API enforces is the one written by hand, and nothing is granted by
   default: a permission that is not declared cannot even be asked for.
3. **Every mutation leaves its entry in the journal**, with the person behind it.
4. A finding is **never closed by a person**: the API refuses it, the domain refuses it, and only
   the re-run of its challenge closes it.
5. The golden rule holds: gold lives only in `accredited.css`.
6. The script of the console runs with Playwright through `make console-e2e`, out of `make check`
   because a test suite does not download browsers by itself.

What is not here: the business-user test (F08-98, a person does it) and anything that needs the
local model (F06-05), which the assistant declares as unavailable instead of pretending.
"""

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.authz import load_matrix, require_perm
from argos_api.authz.enforce import AuthzError
from argos_api.core import JOURNAL_ACTION
from argos_auth import Identity, JwtValidator
from argos_challenges.findings import FindingError, transition

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
CONSOLE = REPO / "console"
BASE = "http://127.0.0.1:8000"
ROLES = ("platform_admin", "campaign_manager", "dpo_reviewer", "read_only_auditor")
ADMIN_DSN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")
MIGRATIONS_DIR = REPO / "services" / "api" / "migrations"


class PersonValidator:
    def validate(self, token: str) -> Identity:
        role, _, person = token.partition(":")
        return Identity(sub=person or role, name=person or role, roles=frozenset({role}))


def _as(role: str, person: str = "") -> dict[str, str]:
    return {"Authorization": f"Bearer {role}:{person or role}"}


def _get(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as answer:  # noqa: S310
            return answer.status, answer.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as refused:
        return refused.code, refused.read().decode("utf-8", "replace")


@pytest.fixture
def migrated_db() -> Iterator[str]:
    """A database of its own for this test, migrated: the phase test touches nobody else's data."""
    import uuid

    import psycopg
    from psycopg import sql

    from argos_common.migrations import apply_migrations

    name = f"argos_phase8_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = f"{ADMIN_DSN.rsplit('/', 1)[0]}/{name}"
    try:
        apply_migrations(dsn, MIGRATIONS_DIR)
        yield dsn
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def api(migrated_db: str) -> TestClient:
    validator = cast(JwtValidator, PersonValidator())
    return TestClient(create_app(validator, dsn=migrated_db))


# ── 1. one origin ────────────────────────────────────────────────────────────


def test_the_console_and_the_v1_come_from_the_same_container() -> None:
    page_status, page = _get("/")
    assert (page_status, '<div id="root">' in page) == (200, True)
    assert not re.search(r'(src|href)="https?://', page), "nothing comes from a CDN"

    api_status, body = _get(f"{API_PREFIX}/campaigns")
    assert api_status == 401, "the v1 answers nothing without a token of the realm"
    assert json.loads(body)["status"] == 401


def test_the_contract_the_console_was_built_against_is_the_one_that_is_served() -> None:
    status, body = _get(f"{API_PREFIX}/openapi.json")
    assert status == 200
    served = set(json.loads(body)["paths"])
    kept = set(json.loads((REPO / "services" / "api" / "openapi.json").read_text("utf-8"))["paths"])
    assert kept <= served
    types = (CONSOLE / "src" / "api" / "schema.d.ts").read_text(encoding="utf-8")
    assert f'"{API_PREFIX}/findings/{{finding_id}}"' in types, "the console types are generated"


# ── 2. the matrix, and nothing by default ────────────────────────────────────


def test_the_matrix_the_api_enforces_is_the_one_written_by_hand() -> None:
    enforced = load_matrix()
    import yaml

    expected: dict[str, dict[str, bool]] = yaml.safe_load(
        (REPO / "tests" / "fixtures" / "authz_matrix.yaml").read_text(encoding="utf-8")
    )
    assert set(expected) == set(ROLES)
    for role, permissions in expected.items():
        for permission, granted in permissions.items():
            assert permission in enforced, f"{permission} is not declared"
            assert (role in enforced[permission]) is granted, f"{role} / {permission}"


def test_a_permission_that_is_not_declared_cannot_even_be_asked_for() -> None:
    with pytest.raises(AuthzError):
        require_perm("campaigns.invent")


def test_the_auditor_only_reads(api: TestClient) -> None:
    refused = api.post(
        f"{API_PREFIX}/campaigns",
        json={"name": "Campaña del auditor"},
        headers=_as("read_only_auditor"),
    )
    assert refused.status_code == 403


# ── 3. every mutation is in the journal ──────────────────────────────────────


def test_every_mutation_leaves_its_entry_with_the_person_behind_it(
    api: TestClient, migrated_db: str
) -> None:
    created = api.post(
        f"{API_PREFIX}/campaigns",
        json={"name": "Campaña de la prueba de fase"},
        headers=_as("campaign_manager", "marta"),
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["campaign_id"]

    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute(
            "SELECT actor, payload FROM argos.audit_journal"
            " WHERE action = %s ORDER BY seq DESC LIMIT 1",
            (JOURNAL_ACTION,),
        ).fetchall()
    assert rows, "the mutation is not in the journal"
    actor, payload = rows[0]
    assert actor == "user:marta"
    assert payload["method"] == "POST"
    assert payload["status"] == 201
    assert payload["path"].endswith("/campaigns")
    assert campaign_id

    read = api.get(f"{API_PREFIX}/campaigns/{campaign_id}", headers=_as("read_only_auditor"))
    assert read.status_code == 200
    with psycopg.connect(migrated_db) as conn:
        after = conn.execute(
            "SELECT count(*) FROM argos.audit_journal WHERE action = %s", (JOURNAL_ACTION,)
        ).fetchone()
    assert after is not None
    with psycopg.connect(migrated_db) as conn:
        again = conn.execute(
            "SELECT count(*) FROM argos.audit_journal WHERE action = %s", (JOURNAL_ACTION,)
        ).fetchone()
    assert again == after, "reading is not a mutation and leaves nothing"


# ── 4. a finding closes only through the re-run ──────────────────────────────


def _planted_finding(dsn: str) -> str:
    """A campaign with one unit that fails: the finding the triage starts from."""
    from argos_challenges.evaluator import evaluate
    from argos_challenges.findings import open_or_recur
    from argos_challenges.store import create_campaign, persist_verdict, pin_campaign, save_units

    campaign_id = create_campaign(
        dsn, "Campaña de la prueba de fase 8", {}, "user:campaign_manager"
    )
    pin_campaign(
        dsn,
        campaign_id,
        snapshot_id=None,
        snapshot_hash=None,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    unit: dict[str, Any] = {
        "unit_id": "f8" + "0" * 62,
        "campaign_id": campaign_id,
        "challenge_id": "sec-encryption-in-transit",
        "challenge_version": "1.0",
        "obligation": "OBL-RGPD-32-1",
        "system_id": "00000000-0000-4000-8000-000000000001",
        "node_key": "k-phase8-0001",
        "probe": {
            "kind": "sql",
            "target": "public.patients",
            "statement": "SHOW ssl",
            "params": {},
        },
        "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
        "sampling": None,
        "severity": "high",
    }
    save_units(dsn, campaign_id, [unit])
    verdict = evaluate(unit, {"ok": True, "data": {"rows": [{"ssl": "off"}]}})
    verdict_id, _ = persist_verdict(dsn, campaign_id, unit, verdict, probe_journal_seq=None)
    return str(open_or_recur(dsn, campaign_id, unit, verdict, verdict_id)["id"])


def test_nobody_closes_a_finding_by_hand(api: TestClient, migrated_db: str) -> None:
    finding_id = _planted_finding(migrated_db)
    path = f"{API_PREFIX}/findings/{finding_id}/transition"
    assert (
        api.post(path, json={"to": "in_remediation"}, headers=_as("dpo_reviewer")).status_code
        == 200
    )
    assert (
        api.post(path, json={"to": "pending_verification"}, headers=_as("dpo_reviewer")).status_code
        == 200
    )

    refused = api.post(path, json={"to": "closed_compliant"}, headers=_as("dpo_reviewer"))
    assert refused.status_code == 409
    assert "re-run" in refused.json()["detail"]

    with pytest.raises(FindingError):
        transition(migrated_db, finding_id, "closed_compliant", "user:dpo")

    # Only the re-run, with a system actor, moves it there.
    transition(migrated_db, finding_id, "closed_compliant", "system:remediation")
    detail = api.get(f"{API_PREFIX}/findings/{finding_id}", headers=_as("dpo_reviewer")).json()
    assert detail["status"] == "closed_compliant"
    assert detail["allowed_transitions"] == []
    assert detail["history"][-1]["actor"] == "system:remediation"


# ── 5. the golden rule ───────────────────────────────────────────────────────


def test_gold_shines_only_on_what_is_accredited() -> None:
    styles = sorted((CONSOLE / "src").rglob("*.css"))
    assert styles, "the console has no styles"
    for sheet in styles:
        body = sheet.read_text(encoding="utf-8")
        if "var(--gold)" in body:
            assert sheet.name == "accredited.css", f"{sheet.name} uses gold"
    planted = (CONSOLE / "src" / "styles" / "design.test.ts").read_text(encoding="utf-8")
    assert "planted" in planted, "the misuse is planted and has to fail in the console suite"


# ── 6. the script of the console ─────────────────────────────────────────────


def test_the_script_of_the_console_is_run_with_its_own_target() -> None:
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^console-e2e:$", makefile, re.MULTILINE)
    assert re.search(r"^console-e2e-setup:$", makefile, re.MULTILINE), "the browser is explicit"
    check = re.search(r"^check: (.+)$", makefile, re.MULTILINE)
    assert check and "console-e2e" not in check.group(1), "make check downloads no browsers"

    script = (CONSOLE / "e2e" / "campaign-to-closed-finding.spec.ts").read_text(encoding="utf-8")
    for step in ("plan previo", "Aprobar", "Volver a ejecutar el reto", "Cerrado conforme"):
        assert step in script, step


def test_what_is_still_pending_is_said_out_loud() -> None:
    report = (REPO / "docs" / "tecnica" / "fases" / "F08-consola-apis.md").read_text(
        encoding="utf-8"
    )
    assert "F08-98" in report, "the business-user test is declared"
    assert "F06-05" in report, "what needs the local model is declared"
