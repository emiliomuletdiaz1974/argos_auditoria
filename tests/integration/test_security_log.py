"""The security log against PostgreSQL and the API (F09-08, ENS op.exp.8, DP-14).

The functional journal says what the product did; the security log, who tried what. It lives in
its own schema with its own chain (the algorithm of the journal v1, another genesis), is written
only through `security.append` by members of `svc_security_writer`, and nobody rewrites it.
Every place that records leaves its event, and no event carries data of the client.
"""

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from argos_ai.guardrails import scrub_input
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from psycopg import sql

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_auth import AuthError, Identity, JwtValidator
from argos_common import security_log
from argos_ontology.bundle import BundleRejectedError, load_bundle

from .test_ontology_bundle import _signed

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(REPO / "deploy" / "dev" / "compose.yaml")]
BEARER = {"Authorization": "Bearer a-token"}


def _events(dsn: str) -> list[dict[str, Any]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT seq, actor, source, kind, outcome, detail FROM security.events ORDER BY seq"
        ).fetchall()
    return [
        {"seq": r[0], "actor": r[1], "source": r[2], "kind": r[3], "outcome": r[4], "detail": r[5]}
        for r in rows
    ]


# --- the chain ---


def test_the_chain_verifies_and_is_not_the_journal(migrated_db: str) -> None:
    with psycopg.connect(migrated_db) as conn:
        journal_before = conn.execute("SELECT count(*) FROM argos.audit_journal").fetchone()
    log = security_log.log(migrated_db)
    for n in range(3):
        log.record("authz.denied", f"user:u{n}", "refused", {"permission": "x"}, source="test")
    result = security_log.verify_chain(migrated_db)
    assert result.intact and result.verified == 3
    with psycopg.connect(migrated_db) as conn:
        journal_after = conn.execute("SELECT count(*) FROM argos.audit_journal").fetchone()
    assert journal_before == journal_after, "the security log has its own chain"


def test_a_changed_byte_breaks_the_chain(migrated_db: str) -> None:
    log = security_log.log(migrated_db)
    for n in range(3):
        log.record("authz.denied", f"user:u{n}", "refused", {"permission": "x"}, source="test")
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute("ALTER TABLE security.events DISABLE TRIGGER USER")
        conn.execute("UPDATE security.events SET actor = 'user:v1' WHERE seq = 2")
        conn.execute("ALTER TABLE security.events ENABLE TRIGGER USER")
    result = security_log.verify_chain(migrated_db)
    assert not result.intact
    assert result.anomalies[0].seq == 2


def test_a_changed_column_outside_the_hash_is_also_seen(migrated_db: str) -> None:
    security_log.log(migrated_db).record(
        "authz.denied", "user:u", "refused", {"permission": "x"}, source="test"
    )
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute("ALTER TABLE security.events DISABLE TRIGGER USER")
        conn.execute("""UPDATE security.events SET detail = '{"permission": "y"}'""")
        conn.execute("ALTER TABLE security.events ENABLE TRIGGER USER")
    assert not security_log.verify_chain(migrated_db).intact


def test_nobody_rewrites_the_log(migrated_db: str) -> None:
    security_log.log(migrated_db).record("authz.denied", "user:u", "refused", {}, source="test")
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        for statement in (
            "UPDATE security.events SET actor = 'x'",
            "DELETE FROM security.events",
            "TRUNCATE security.events",
        ):
            with pytest.raises(psycopg.errors.RaiseException):
                conn.execute(statement)


@pytest.mark.parametrize(
    ("role", "privilege", "expected"),
    [
        ("svc_api", "UPDATE", False),
        ("svc_api", "DELETE", False),
        ("svc_api", "INSERT", False),
        ("svc_api", "SELECT", True),
        ("svc_ai_gateway", "SELECT", False),
    ],
)
def test_the_table_is_written_by_its_function_alone(
    migrated_db: str, role: str, privilege: str, expected: bool
) -> None:
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT has_table_privilege(%s, 'security.events', %s)", (role, privilege)
        ).fetchone()
    assert row == (expected,)


@pytest.mark.parametrize(
    ("role", "expected"),
    [("svc_api", True), ("svc_challenge", True), ("svc_ontology", True), ("svc_ai_gateway", False)],
)
def test_who_may_write_the_log(migrated_db: str, role: str, expected: bool) -> None:
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT has_function_privilege(%s, 'security.append(text, text, text)', 'EXECUTE')",
            (role,),
        ).fetchone()
    assert row == (expected,)


def test_a_member_of_the_writer_role_appends(migrated_db: str) -> None:
    name, password = f"probe_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE svc_api").format(
                sql.Identifier(name), sql.Literal(password)
            )
        )
    host = migrated_db.split("@", 1)[1]
    try:
        security_log.log(f"postgresql://{name}:{password}@{host}").record(
            "authz.denied", "user:u", "refused", {"permission": "x"}, source="test"
        )
        assert _events(migrated_db)[-1]["kind"] == "authz.denied"
    finally:
        with psycopg.connect(migrated_db, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


# --- the places that record ---


class Tokens:
    """A token per role, and one that is refused."""

    def validate(self, token: str) -> Identity:
        if token == "forged":
            raise AuthError("invalid token: InvalidSignatureError")
        role, _, factor = token.partition("+")
        amr = frozenset({"pwd", "otp"} if factor == "otp" else {"pwd"})
        return Identity(sub=f"person-{role}", name=role, roles=frozenset({role}), amr=amr)


def _client(dsn: str) -> TestClient:
    app = create_app(cast(JwtValidator, Tokens()), dsn=dsn)
    probe = APIRouter(route_class=CoreRoute)

    @probe.post("/probe-admin", dependencies=[Depends(require_perm("credentials.revoke"))])
    def admin_action() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(probe, prefix=API_PREFIX)
    return TestClient(app)


def _as(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_every_place_that_records_leaves_its_event(migrated_db: str) -> None:
    client = _client(migrated_db)
    client.get(f"{API_PREFIX}/campaigns", headers=_as("forged"))
    client.post(f"{API_PREFIX}/campaigns", json={"name": "x"}, headers=_as("read_only_auditor"))
    client.post(f"{API_PREFIX}/findings/f-1/transition", json={}, headers=_as("dpo_reviewer"))
    client.post(f"{API_PREFIX}/probe-admin", headers=_as("platform_admin+otp"))
    security_log.log(migrated_db).flush()

    kinds = {(e["kind"], e["outcome"]) for e in _events(migrated_db)}
    assert ("auth.token_rejected", "refused") in kinds
    assert ("authz.denied", "refused") in kinds
    assert ("authz.second_factor_required", "refused") in kinds
    assert ("authz.admin_action", "allowed") in kinds


def test_a_rejected_content_signature_leaves_its_event(migrated_db: str) -> None:
    bundle, signature, public_key, fingerprint = _signed("1.0.0")
    forged = bytes([signature[0] ^ 1]) + signature[1:]
    with pytest.raises(BundleRejectedError):
        load_bundle(migrated_db, bundle, forged, public_key, fingerprint=fingerprint)
    [event] = [e for e in _events(migrated_db) if e["kind"] == "content.signature_rejected"]
    assert event["outcome"] == "refused"
    assert "bundle_sha256" in event["detail"]


def test_no_event_carries_data_of_the_client(migrated_db: str) -> None:
    client = _client(migrated_db)
    # A path and a body with personal data: the log keeps the route, never the contents.
    client.post(
        f"{API_PREFIX}/campaigns",
        json={"name": "Juan Pérez 12345678Z"},
        headers=_as("read_only_auditor"),
    )
    client.get(f"{API_PREFIX}/inventory/nodes/12345678Z", headers=_as("forged"))
    security_log.log(migrated_db).flush()
    for event in _events(migrated_db):
        text = json.dumps(event["detail"], ensure_ascii=False) + event["actor"]
        _, substitutions = scrub_input(text)
        assert substitutions == 0, event


def test_a_burst_of_refusals_does_not_fill_the_log(migrated_db: str) -> None:
    client = _client(migrated_db)
    for _ in range(200):
        client.get(f"{API_PREFIX}/campaigns", headers=_as("forged"))
    security_log.log(migrated_db).flush()
    rejected = [e for e in _events(migrated_db) if e["kind"] == "auth.token_rejected"]
    assert len(rejected) <= security_log.PER_WINDOW + 1
    assert sum(e["detail"].get("suppressed", 1) for e in rejected) == 200


# --- reading it ---


@pytest.mark.parametrize(
    ("role", "status"), [("platform_admin", 200), ("read_only_auditor", 200), ("dpo_reviewer", 403)]
)
def test_the_log_is_read_by_the_administrator_and_the_auditor(
    migrated_db: str, role: str, status: int
) -> None:
    security_log.log(migrated_db).record("authz.denied", "user:u", "refused", {}, source="test")
    answer = _client(migrated_db).get(f"{API_PREFIX}/security/events", headers=_as(role))
    assert answer.status_code == status
    if status == 200:
        items = answer.json()["items"]
        assert items and {"seq", "at", "actor", "source", "kind", "outcome", "detail"} <= set(
            items[0]
        )


def test_the_log_is_paged_by_cursor(migrated_db: str) -> None:
    log = security_log.log(migrated_db)
    for n in range(5):
        log.record("authz.denied", f"user:u{n}", "refused", {}, source="test")
    client = _client(migrated_db)
    first = client.get(f"{API_PREFIX}/security/events?limit=3", headers=_as("platform_admin"))
    body = first.json()
    assert len(body["items"]) == 3 and body["next"]
    second = client.get(
        f"{API_PREFIX}/security/events?limit=3&cursor={body['next']}", headers=_as("platform_admin")
    ).json()
    seen = [i["seq"] for i in body["items"] + second["items"]]
    assert sorted(seen, reverse=True) == seen and len(set(seen)) == 5


# --- alerts ---


def test_the_metrics_say_how_many_and_whether_the_chain_holds(migrated_db: str) -> None:
    security_log.log(migrated_db).record("authz.denied", "user:u", "refused", {}, source="test")
    text = _client(migrated_db).get("/metrics").text
    assert 'argos_security_events_total{kind="authz.denied",outcome="refused"} 1' in text
    assert "argos_security_chain_ok 1" in text


def test_the_alert_rules_load_in_prometheus() -> None:
    check = subprocess.run(  # noqa: S603 - fixed command against the development environment
        [
            *COMPOSE,
            "exec",
            "-T",
            "prometheus",
            "promtool",
            "check",
            "rules",
            "/etc/prometheus/rules/security.yml",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    rules = (REPO / "deploy" / "dev" / "prometheus" / "rules" / "security.yml").read_text("utf-8")
    for alert in ("SecurityRefusalBurst", "SecurityChainBroken", "SecuritySignatureRejected"):
        assert f"alert: {alert}" in rules
