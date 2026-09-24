"""ARG-090 · the airlock against the development environment (F09-13).

The whole cycle of isolated stamping: the airlock exports the queries of what waits for its time
stamp, a TSA outside the appliance stamps them (the development TSA stands for it), and the replies
come back through the airlock, verified before they are kept. Then a real dossier and its
credential leave through it, checked against the hashes they were recorded with. Every step is in
the journal and the security log.
"""

import datetime as dt
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

import httpx
import psycopg
import pytest
from cryptography import x509

from argos_airgap import Gate, recorder
from argos_airgap.exporters import credential_exporter, dossier_exporter, tsq_exporter
from argos_airgap.importers import tsr_importer
from argos_evidence.tsa import accept_reply, http_transport, stamp_of

from .conftest import ADMIN_DSN
from .test_tsa import TSA, _signed, _store

pytestmark = pytest.mark.integration


def _gate(tmp_path: Path, dsn: str, record_dsn: str) -> Gate:
    store = _store()
    roots = [x509.load_pem_x509_certificate(httpx.get(f"{TSA}/ca.pem").content)]
    until = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)

    def queued() -> list[str]:
        with psycopg.connect(dsn) as conn:
            rows = conn.execute(
                "SELECT object_key FROM argos.tsa_queue WHERE status = 'queued'"
            ).fetchall()
        return [str(row[0]) for row in rows]

    for folder in ("in", "out", "work"):
        (tmp_path / folder).mkdir()
    return Gate(
        tmp_path / "in",
        tmp_path / "out",
        tmp_path / "work",
        importers={
            "tsr": tsr_importer(
                queued, lambda key, reply: accept_reply(dsn, store, key, reply, roots, until)
            )
        },
        exporters={
            "tsq": tsq_exporter(dsn, store),
            "dossier": dossier_exporter(dsn, store),
            "credential": credential_exporter(dsn, store),
        },
        record=recorder(record_dsn),
    )


def _journal(dsn: str, action: str) -> list[dict[str, object]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT actor, payload FROM argos.audit_journal WHERE action = %s ORDER BY seq",
            (action,),
        ).fetchall()
    return [{"actor": actor, **payload} for actor, payload in rows]


def test_isolated_stamping_goes_out_and_comes_back_through_the_airlock(
    tmp_path: Path, migrated_db: str
) -> None:
    key = _signed(migrated_db, _store())
    gate = _gate(tmp_path, migrated_db, migrated_db)

    exported = gate.export("tsq", "user:admin.test", {})
    [query] = exported.files
    assert query["name"].endswith(".tsq")

    outside = http_transport(TSA)  # stands for the TSA outside the appliance
    folder = gate.outbox / exported.id
    for sent in folder.glob("*.tsq"):
        (gate.inbox / sent.name.replace(".tsq", ".tsr")).write_bytes(outside(sent.read_bytes()))
    (gate.inbox / ("0" * 32 + ".tsr")).write_bytes(b"a reply nobody asked for")

    results = {r.file: r for r in gate.scan("user:admin.test")}
    imported = [r for r in results.values() if r.result == "imported"]
    assert len(imported) == 1, results
    assert results["0" * 32 + ".tsr"].result == "rejected"
    stamp = stamp_of(migrated_db, key)
    assert stamp is not None and stamp.status == "stamped"

    exports = _journal(migrated_db, "airgap.export")
    imports = _journal(migrated_db, "airgap.import")
    assert exports[0]["actor"] == "user:admin.test" and exports[0]["kind"] == "tsq"
    assert {entry["outcome"] for entry in imports} == {"succeeded", "refused"}
    assert all(len(str(entry["sha256"])) == 64 for entry in imports)


def test_a_dossier_and_its_credential_leave_checked_against_their_hashes(
    tmp_path: Path, migrated_db: str
) -> None:
    with psycopg.connect(ADMIN_DSN) as conn:
        row = conn.execute(
            "SELECT d.campaign_id::text, d.sha256 FROM argos.dossiers d"
            " JOIN argos.credentials c ON c.dossier_sha256 = d.sha256"
            " ORDER BY d.created_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("the development environment has no dossier with a credential yet")
    campaign, sha256 = row
    gate = _gate(tmp_path, ADMIN_DSN, migrated_db)

    dossier = gate.export("dossier", "user:admin.test", {"campaign_id": campaign})
    names = {f["name"]: f for f in dossier.files}
    assert names[f"dossier-{campaign}.json"]["sha256"] == sha256
    assert f"dossier-{campaign}.pdf" in names

    credential = gate.export("credential", "user:admin.test", {"campaign_id": campaign})
    [issued] = credential.files
    document = json.loads((gate.outbox / credential.id / issued["name"]).read_bytes())
    assert sha256 in json.dumps(document)

    with pytest.raises(PermissionError):
        gate.export("database", "user:admin.test", {})
    outcomes = [(e["kind"], e["outcome"]) for e in _journal(migrated_db, "airgap.export")]
    assert outcomes == [
        ("dossier", "succeeded"),
        ("credential", "succeeded"),
        ("database", "refused"),
    ], "the refused export is written down too"
    with psycopg.connect(migrated_db) as conn:
        refused = conn.execute(
            "SELECT count(*) FROM security.events WHERE kind = 'airgap.export'"
            " AND outcome = 'refused'"
        ).fetchone()
    assert refused is not None and refused[0] >= 1
    assert hashlib.sha256(b"").hexdigest() not in {f["sha256"] for f in dossier.files}


def test_the_deployed_api_offers_the_airlock_only_with_a_token() -> None:
    for route in ("imports", "exports"):
        request = urllib.request.Request(  # noqa: S310 - the development API on the loopback
            f"http://127.0.0.1:8000/api/v1/airgap/{route}", method="POST", data=b""
        )
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=10)  # noqa: S310
        assert refused.value.code == 401
