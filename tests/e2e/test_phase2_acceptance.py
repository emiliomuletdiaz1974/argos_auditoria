"""Phase 2 acceptance test (Plan Director §8.2 "Fase 02").

Against the simulated demonstration environment ARGOS discovers and samples the six source types
without a single write, verified in each server's own records and not only in ours; the write
harness fails on every path, and every probe has its prior journal entry.
"""

import importlib.util
import os
import re
import ssl
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pymysql
import pytest
from integration.sources import ROOT, open_source_connector
from ldap3 import NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPConnectionIsReadOnlyError

from argos_common.errors import ReadOnlyViolationError
from argos_common.journal_pg import PostgresJournal
from argos_connector.probes import ProbeSpec
from argos_connector.testing import (
    assert_http_writes_rejected,
    assert_no_write_surface,
    assert_sql_writes_rejected,
)
from argos_dicom.connector import DicomConnector
from argos_fhir.connector import FhirConnector
from argos_files.connector import FilesConnector
from argos_ldap.connector import LdapConnector
from argos_rest.connector import RestConnector
from argos_sql.generic import SqlConnector
from argos_sql.postgres import PostgresConnector

pytestmark = pytest.mark.integration

DEV_DSN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")
COMPOSE = [
    "docker",
    "compose",
    "-f",
    str(ROOT / "deploy" / "dev" / "compose.yaml"),
    "--profile",
    "sources",
]
SOURCES_DIR = ROOT / "deploy" / "dev" / "sources"
KEYCLOAK = "http://127.0.0.1:8180"
# HAPI reuses a search result for about a minute: a cached total would make before == after.
NO_CACHE = {"Cache-Control": "no-cache"}
WRITE_VERB = re.compile(
    r"^\s*(insert|update|delete|merge|replace|create|drop|alter|truncate|grant|revoke|copy|call"
    r"|lock)\b",
    re.IGNORECASE,
)
SIX_TYPES = {"rdbms", "files", "directory", "api", "clinical.fhir", "clinical.dicom"}
ORTHANC_COUNTERS = ("CountPatients", "CountStudies", "CountSeries", "CountInstances")

_spec = importlib.util.spec_from_file_location("prepare", ROOT / "tools" / "prepare_dev_sources.py")
assert _spec is not None and _spec.loader is not None
prepare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prepare)


# ---------- server-side evidence ----------
@dataclass(frozen=True)
class Evidence:
    files: dict[str, str]
    bucket: dict[str, str]
    fhir_history: int
    orthanc: dict[str, int]
    keycloak: tuple[int, int]


def _keycloak_realm() -> tuple[int, int]:
    token = httpx.post(
        f"{KEYCLOAK}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": "admin",
        },
        timeout=30,
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    admin = f"{KEYCLOAK}/admin/realms/argos"
    users = int(httpx.get(f"{admin}/users/count", headers=headers, timeout=30).json())
    clients = len(httpx.get(f"{admin}/clients", headers=headers, timeout=30).json())
    return users, clients


def _snapshot() -> Evidence:
    statistics = httpx.get("http://127.0.0.1:8042/statistics", timeout=30).json()
    history = httpx.get(
        "http://127.0.0.1:8090/fhir/_history",
        params={"_summary": "count"},
        headers=NO_CACHE,
        timeout=30,
    ).json()
    return Evidence(
        files=prepare.tree_manifest(SOURCES_DIR / "files" / "clinical"),
        bucket=prepare.tree_manifest(SOURCES_DIR / "s3" / "clinical-archive"),
        fhir_history=int(history["total"]),
        orthanc={k: int(statistics[k]) for k in ORTHANC_COUNTERS},
        keycloak=_keycloak_realm(),
    )


def _postgres_writes_by_argos(since: datetime) -> list[str]:
    logs = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        [*COMPOSE, "logs", "--since", since.strftime("%Y-%m-%dT%H:%M:%SZ"), "source-postgres"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [
        line
        for line in logs.splitlines()
        if "user=argos_ro" in line
        and "statement:" in line
        and WRITE_VERB.search(line.split("statement:", 1)[1])
    ]


def _mariadb_writes_by_argos(since: datetime) -> list[str]:
    conn = pymysql.connect(host="127.0.0.1", port=53306, user="root", password="")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT CONVERT(argument USING utf8mb4) FROM mysql.general_log "
                "WHERE user_host LIKE 'argos_ro%%' AND command_type = 'Query' AND event_time >= %s",
                (since.replace(tzinfo=None),),
            )
            return [row[0] for row in cur.fetchall() if WRITE_VERB.search(row[0])]
    finally:
        conn.close()


def _directory_changes_since(since: datetime) -> list[str]:
    # ldap3 matches the host only against DNS names, not IP SANs: accept the certificate's name.
    tls = Tls(
        validate=ssl.CERT_REQUIRED,
        ca_certs_file=str(SOURCES_DIR / "certs" / "ca.crt"),
        valid_names=["localhost"],
    )
    server = Server("127.0.0.1", port=1636, use_ssl=True, tls=tls, get_info=NONE)
    admin = Connection(
        server, user="cn=admin,dc=hosp,dc=local", password="dev-only-admin", auto_bind=True
    )
    stamp = since.strftime("%Y%m%d%H%M%SZ")
    admin.search(
        "dc=hosp,dc=local", f"(|(modifyTimestamp>={stamp})(createTimestamp>={stamp}))", SUBTREE
    )
    changed = [str(e.entry_dn) for e in admin.entries]
    admin.unbind()
    return changed


# ---------- sources, probes and write harness per type ----------
def _sql_harness(connector: Any) -> None:
    assert_sql_writes_rejected(connector, "t")


def _files_harness(connector: Any) -> None:
    assert_no_write_surface(FilesConnector)
    assert_no_write_surface(type(connector.backend))
    with pytest.raises(ReadOnlyViolationError):
        connector.execute(ProbeSpec("scan_schema", "../outside"))


def _ldap_harness(connector: Any) -> None:
    assert_no_write_surface(LdapConnector)
    with pytest.raises(LDAPConnectionIsReadOnlyError):
        connector.connection.delete("uid=syn.user1,ou=people,dc=hosp,dc=local")


def _http_harness(path: str) -> Callable[[Any], None]:
    def harness(connector: Any) -> None:
        assert_no_write_surface(type(connector))
        assert_http_writes_rejected(lambda method, target: connector._request(method, target), path)

    return harness


def _dicom_harness(connector: Any) -> None:
    assert_no_write_surface(DicomConnector)
    assert connector.execute(ProbeSpec("check_config", "pacs")).data["retrieve_capable"] is False


@dataclass(frozen=True)
class Source:
    name: str
    connector: type
    source_type: str
    discover: ProbeSpec
    sample: ProbeSpec
    harness: Callable[[Any], None]


SOURCES = (
    Source(
        "dev-source-postgres",
        PostgresConnector,
        "rdbms",
        ProbeSpec("scan_schema", "clinic"),
        ProbeSpec("sample", "clinic.patients", params={"columns": ["national_id"], "k": 10}),
        _sql_harness,
    ),
    Source(
        "dev-source-mariadb",
        SqlConnector,
        "rdbms",
        ProbeSpec("scan_schema", "billing", params={"schemas": ["billing"]}),
        ProbeSpec("sample", "billing.invoices", params={"columns": ["patient_ref"], "k": 10}),
        _sql_harness,
    ),
    Source(
        "dev-files-smb",
        FilesConnector,
        "files",
        ProbeSpec("scan_schema", ""),
        ProbeSpec("sample", "radiology", params={"k": 10}),
        _files_harness,
    ),
    Source(
        "dev-files-s3",
        FilesConnector,
        "files",
        ProbeSpec("scan_schema", ""),
        ProbeSpec("sample", "", params={"k": 10}),
        _files_harness,
    ),
    Source(
        "dev-directory-ldap",
        LdapConnector,
        "directory",
        ProbeSpec("scan_schema", "dc=hosp,dc=local"),
        ProbeSpec("sample", "dc=hosp,dc=local", params={"k": 10}),
        _ldap_harness,
    ),
    Source(
        "dev-api-keycloak",
        RestConnector,
        "api",
        ProbeSpec("scan_schema", "*"),
        ProbeSpec(
            "sample",
            "/realms/argos/protocol/openid-connect/certs",
            params={"fields": ["kid"], "k": 5},
        ),
        _http_harness("/realms/argos"),
    ),
    Source(
        "dev-clinical-fhir",
        FhirConnector,
        "clinical.fhir",
        ProbeSpec("scan_schema", "*"),
        ProbeSpec("sample", "/Patient", params={"fields": ["resource.gender"], "k": 10}),
        _http_harness("/Patient"),
    ),
    Source(
        "dev-clinical-dicom",
        DicomConnector,
        "clinical.dicom",
        ProbeSpec("scan_schema", "*"),
        ProbeSpec("sample", "*", params={"k": 10}),
        _dicom_harness,
    ),
)


def test_phase2_reads_six_source_types_without_a_single_write() -> None:
    assert {s.source_type for s in SOURCES} == SIX_TYPES
    journal = PostgresJournal(DEV_DSN)
    head_before = journal.head()[0]
    started = datetime.now(UTC) - timedelta(seconds=2)
    before = _snapshot()

    system_ids = []
    for source in SOURCES:
        connector = open_source_connector(source.name, source.connector, DEV_DSN)
        try:
            discovered = connector.execute(source.discover)
            sampled = connector.execute(source.sample)
            assert discovered.ok and sampled.ok, (source.name, discovered.data, sampled.data)
            assert discovered.rows_touched > 0 and sampled.rows_touched > 0, source.name
            source.harness(connector)
        finally:
            connector.close()
        system_ids.append(connector.system_id)

    # 1) Server-side evidence: no write reached any customer system.
    after = _snapshot()
    assert _postgres_writes_by_argos(started) == []
    assert _mariadb_writes_by_argos(started) == []
    assert _directory_changes_since(started) == []
    assert after == before

    # 2) Journal evidence: every probe journaled before emission, nothing left open, chain intact.
    with psycopg.connect(DEV_DSN) as conn:
        statuses = conn.execute(
            "SELECT system_id::text, status, count(*) FROM argos.connector_queries "
            "WHERE journal_seq > %s GROUP BY 1, 2",
            (head_before,),
        ).fetchall()
    by_system: dict[str, dict[str, int]] = {}
    for system_id, status, count in statuses:
        by_system.setdefault(system_id, {})[status] = int(count)
    assert set(by_system) == set(system_ids)
    assert all(counts.get("emitted", 0) == 0 for counts in by_system.values())
    assert all(counts.get("completed", 0) >= 2 for counts in by_system.values())
    closed = sum(c.get("completed", 0) + c.get("failed", 0) for c in by_system.values())
    emitted_entries = sum(
        1
        for entry in journal.read(from_seq=head_before + 1)
        if entry.action == "query.emit" and entry.actor.startswith("system:connector:")
    )
    assert emitted_entries == closed
    assert journal.verify().intact
