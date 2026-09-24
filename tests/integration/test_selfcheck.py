"""ARG-100 · the self-* campaign end to end, in a database of its own (F10-01).

The campaign runs the real engine against an appliance database: the SQL connector reads its facts
with the login of `svc_selfcheck`, the campaign seals, the evidence chain writes the dossier, and
the release gate reads it. Each test uses a disposable database, registered as a system of its
own, so the development appliance and its credential are not touched.
"""

import importlib.util
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import hvac
import psycopg
import pytest
from psycopg import sql

from argos_common.journal_pg import PostgresJournal
from argos_health.monitor import Monitor

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]


def _selfcheck() -> ModuleType:
    spec = importlib.util.spec_from_file_location("selfcheck", REPO / "tools" / "selfcheck.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selfcheck = _selfcheck()


@pytest.fixture
def appliance(migrated_db: str) -> Iterator[str]:
    """The disposable database as an appliance: its system, signed content and a recent restore."""
    system_id = _appliance(migrated_db)
    yield system_id
    vault = hvac.Client(url=selfcheck.DEV_VAULT, token=selfcheck.DEV_VAULT_TOKEN)
    vault.secrets.kv.v2.delete_metadata_and_all_versions(
        path=f"connectors/{system_id}", mount_point="argos"
    )


def _appliance(dsn: str) -> str:
    system_id = str(uuid.uuid4())
    selfcheck.dev_setup(dsn, selfcheck.DEV_VAULT, selfcheck.DEV_VAULT_TOKEN, system_id)
    selfcheck.content_in_force(dsn, True, selfcheck.DEV_VAULT, selfcheck.DEV_VAULT_TOKEN)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.restore_tests (tested_at, result, journal_intact, security_intact,"
            " duration_seconds) VALUES (%s, 'passed', true, true, 1)",
            (datetime.now(UTC) - timedelta(days=1),),
        )
    _observe(dsn)
    return system_id


class _Store:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_immutable(self, key: str, data: bytes, retain_until: datetime) -> None:
        self.objects[key] = data

    def get(self, key: str, version_id: str | None = None) -> bytes:
        return self.objects[key]


def _observe(dsn: str) -> None:
    """A round of the health service (F10-02): nobody runs it on a disposable database."""
    monitor = Monitor(dsn, _Store(), list, None, journal_tail=100)
    monitor.run_all()
    monitor.check_journal(full=True)
    monitor.publish()


def test_a_sound_appliance_passes_with_only_the_trap(
    migrated_db: str, appliance: str, tmp_path: Path
) -> None:
    system_id = appliance
    dossier, folder = selfcheck.run(migrated_db, tmp_path, "test", system_id)
    assert dossier["campaign"]["status"] == "sealed"
    assert dossier["results"]["units"] == len(selfcheck.self_challenges(REPO / "library"))
    assert [f["challenge_id"] for f in dossier["findings"]] == [selfcheck.TRAP]
    assert selfcheck.gate(dossier) == []
    assert (folder / "dossier.json").is_file()
    assert (folder / "dossier.pdf").read_bytes().startswith(b"%PDF")


def test_a_broken_journal_blocks_the_release(
    migrated_db: str, appliance: str, tmp_path: Path
) -> None:
    system_id = appliance
    journal = PostgresJournal(migrated_db)
    head, _ = journal.head()
    table = sql.Identifier("argos", "audit_journal")
    with psycopg.connect(migrated_db) as conn:
        conn.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER USER").format(table))
        conn.execute(
            sql.SQL("UPDATE {} SET payload_canon = payload_canon || ' ' WHERE seq = %s").format(
                table
            ),
            (max(head - 1, 1),),
        )
        conn.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER USER").format(table))
    _observe(migrated_db)  # the health service sees the break at its next round
    campaign_id = selfcheck.run_campaign(migrated_db, "test", system_id)
    with psycopg.connect(migrated_db) as conn:
        findings = dict(
            conn.execute(
                "SELECT challenge_id, severity FROM argos.findings WHERE campaign_id = %s",
                (campaign_id,),
            ).fetchall()
        )
    # The campaign measured the break: the finding of the journal, and the trap.
    assert findings.get("self-001") == "critical"
    assert selfcheck.TRAP in findings
    # And the evidence chain does not anchor a broken journal: no dossier, no release.
    with pytest.raises(selfcheck.SelfcheckError, match="journal"):
        selfcheck.write_dossier(migrated_db, campaign_id, tmp_path, "test")
