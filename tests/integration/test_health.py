"""ARG-094 · the domain health service against PostgreSQL (F10-02).

The monitor runs every check once on a disposable database, with doubles only where the source is
not the database: the WORM store and the certificates of the internal CA. The facts it publishes
reach the self-* challenges through `argos_facts.facts` only while they are fresh.
"""

import datetime as dt
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql

from argos_common.journal_pg import PostgresJournal
from argos_health.measures import render_metrics
from argos_health.monitor import Monitor

pytestmark = pytest.mark.integration

NOW = dt.datetime.now(dt.UTC)
EXPECTED = {
    "argos_journal_verify_ok",
    "argos_worm_healthy",
    "argos_campaigns_running",
    "argos_campaign_gate_waiting_hours",
    "argos_connector_circuit_open",
    "argos_tsa_queue_pending",
    "argos_webhook_deliveries_pending",
    "argos_review_queue_pending",
    "argos_evidence_volume_used_ratio",
    "argos_certs_expiring_7d",
    "argos_job_last_success_timestamp_seconds",
    "argos_scan_last_duration_seconds",
    "argos_health_check_timestamp_seconds",
}


class _Store:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_immutable(self, key: str, data: bytes, retain_until: dt.datetime) -> None:
        self.objects[key] = data

    def get(self, key: str, version_id: str | None = None) -> bytes:
        return self.objects[key]


def _certificates() -> list[dict[str, Any]]:
    return [{"common_name": "api", "not_after": NOW + dt.timedelta(days=25)}]


def _monitor(dsn: str, tmp_path: Path) -> Monitor:
    return Monitor(dsn, _Store(), _certificates, tmp_path, journal_tail=100)


def _facts(dsn: str) -> dict[str, str]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT fact, setting FROM argos_facts.facts").fetchall()
    return {str(fact): str(setting) for fact, setting in rows}


def _with_a_gate_and_a_circuit(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        system = conn.execute(
            "INSERT INTO argos.systems (id, name, kind, environment, connection)"
            " VALUES (gen_random_uuid(), 'health-test', 'rdbms', 'development', '{}')"
            " RETURNING id::text"
        ).fetchone()
        campaign = conn.execute(
            "INSERT INTO argos.campaigns (id, name, status, scope, created_by)"
            " VALUES (gen_random_uuid(), 'health-test', 'pinned', '{}', 'user:test')"
            " RETURNING id"
        ).fetchone()
        assert system is not None and campaign is not None
        conn.execute(
            "INSERT INTO argos.approval_requests (campaign_id, gate, payload, requested_at)"
            " VALUES (%s, 'start', '{}', now() - interval '30 hours')",
            (campaign[0],),
        )
        conn.execute(
            "INSERT INTO argos.scan_runs (id, system_id, status, started_at, finished_at, events)"
            " VALUES (gen_random_uuid(), %s, 'completed', now() - interval '3 hours',"
            " now() - interval '30 minutes', 0)",
            (system[0],),
        )
        conn.execute(
            "INSERT INTO argos.load_budget (system_id, tokens, updated_at, state, opened_at)"
            " VALUES (%s, 0, now(), 'open', now())",
            (system[0],),
        )


def test_every_measure_is_published(migrated_db: str, tmp_path: Path) -> None:
    PostgresJournal(migrated_db).append("user:tester", "test.health", {"n": 1})
    _with_a_gate_and_a_circuit(migrated_db)
    monitor = _monitor(migrated_db, tmp_path)
    monitor.run_all()
    monitor.check_journal(full=True)
    text = render_metrics(monitor.observations())
    names = {line.split("{")[0].split(" ")[0] for line in text.splitlines() if line[:1] != "#"}
    assert names >= EXPECTED
    assert 'argos_journal_verify_ok{scope="tail"} 1' in text
    assert 'argos_journal_verify_ok{scope="full"} 1' in text
    assert "argos_worm_healthy 1" in text
    assert "argos_campaigns_running 1" in text
    assert 'argos_connector_circuit_open{system="health-test"} 1' in text
    [gate] = [o for o in monitor.observations() if o.name == "argos_campaign_gate_waiting_hours"]
    assert gate.labels["gate"] == "start" and 29.9 < gate.value < 30.5
    assert "argos_certs_expiring_7d 0" in text
    # F10-03: the rescan objective of the specification (under 2 hours) is watched per system.
    assert 'argos_scan_last_duration_seconds{system="health-test"} 9000' in text


def test_a_broken_journal_reads_as_not_intact(migrated_db: str, tmp_path: Path) -> None:
    journal = PostgresJournal(migrated_db)
    for n in range(4):
        journal.append("user:tester", "test.health", {"n": n})
    table = sql.Identifier("argos", "audit_journal")
    with psycopg.connect(migrated_db) as conn:
        conn.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER USER").format(table))
        conn.execute(
            sql.SQL("UPDATE {} SET payload_canon = payload_canon || ' ' WHERE seq = 3").format(
                table
            )
        )
        conn.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER USER").format(table))
    monitor = _monitor(migrated_db, tmp_path)
    monitor.check_journal()
    monitor.check_journal(full=True)
    text = render_metrics(monitor.observations())
    assert 'argos_journal_verify_ok{scope="tail"} 0' in text
    assert 'argos_journal_verify_ok{scope="full"} 0' in text


def test_the_published_facts_reach_the_self_check_while_fresh(
    migrated_db: str, tmp_path: Path
) -> None:
    before = _facts(migrated_db)
    assert before["worm_canary_ok"] == "false"  # nobody looked yet
    monitor = _monitor(migrated_db, tmp_path)
    monitor.run_all()
    monitor.publish()
    facts = _facts(migrated_db)
    assert facts["worm_canary_ok"] == "true"
    assert facts["certificates_valid"] == "true"
    assert facts["queues_flowing"] == "true"
    # A silent monitor is not a healthy appliance: stale facts are false.
    with psycopg.connect(migrated_db) as conn:
        conn.execute("UPDATE argos.health_facts SET observed_at = now() - interval '20 minutes'")
    stale = _facts(migrated_db)
    assert stale["worm_canary_ok"] == "false"
    assert stale["certificates_valid"] == "false"


def test_the_health_role_reads_what_it_measures_and_writes_only_its_facts(
    migrated_db: str,
) -> None:
    with psycopg.connect(migrated_db) as conn:
        grants = conn.execute(
            "SELECT table_schema || '.' || table_name, privilege_type"
            " FROM information_schema.role_table_grants WHERE grantee = 'svc_health'"
        ).fetchall()
    writes = sorted({table for table, privilege in grants if privilege != "SELECT"})
    assert writes == ["argos.health_facts"]
    assert ("argos.audit_journal", "SELECT") in grants
    assert ("security.events", "SELECT") in grants
    with psycopg.connect(migrated_db) as conn:
        conn.execute("SET ROLE svc_health")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE argos.campaigns SET status = 'failed'")
