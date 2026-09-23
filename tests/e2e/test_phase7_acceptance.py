"""Phase 7 acceptance test (Plan Director §8.2 "Fase 07").

1. The Phase 5 campaign ends in a dossier, JSON and PDF, kept in the WORM store, and a credential.
2. The Merkle root verifies, and a corrupted piece breaks the verification naming the piece:
   an artifact, the dossier, the signed root, the time stamp token.
3. The WORM store refuses to delete or overwrite a dossier.
4. The credential verifies with the public verifier (the container, as a third party uses it),
   and once revoked it no longer does, without being touched.

The verification with the GXDCH tools needs the participant's registration (F07-14) and does not
gate this phase (F07-00, point 4). The recorded demonstration is done by a person.
"""

import base64
import copy
import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import boto3
import httpx
import psycopg
import pytest
from botocore.exceptions import ClientError

from argos_evidence.credential.issue import revoke_credential
from argos_evidence.worm import EVIDENCE_BUCKET
from argos_verifier.checks import Trust, verify_bundle

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
VERIFIER = "http://127.0.0.1:8007"
ADMIN_DSN = "postgresql://argos@127.0.0.1:55432/argos"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_mvp_demo", REPO / "tools" / "demo" / "run_mvp_demo.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def phase7(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    out = tmp_path_factory.mktemp("phase7")
    script = _script()
    summary = script.run_demo(out, keep_database=True)
    dsn = f"{ADMIN_DSN.rsplit('/', 1)[0]}/{summary['database']}"
    bundle = json.loads((out / "bundle.json").read_text(encoding="utf-8"))
    trust = Trust.from_file(out / "trust.json")
    try:
        yield {"summary": summary, "dsn": dsn, "bundle": bundle, "out": out, "trust": trust}
    finally:
        script._drop_database(dsn)


def _s3() -> Any:
    return boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:7075",
        aws_access_key_id="dev-only-evidence",
        aws_secret_access_key="dev-only-evidence-secret",  # noqa: S106 - development store
        region_name="us-east-1",
    )


def _flip(encoded: str) -> str:
    raw = bytearray(base64.b64decode(encoded))
    raw[len(raw) // 2] ^= 0x01
    return base64.b64encode(bytes(raw)).decode("ascii")


def _failed(bundle: dict[str, Any], trust: Trust) -> list[str]:
    return [c.name for c in verify_bundle(bundle, trust).checks if c.status == "failed"]


def test_the_phase5_campaign_ends_in_a_dossier_and_a_credential(phase7: dict[str, Any]) -> None:
    summary = phase7["summary"]
    assert summary["campaign"]["status"] == "sealed"
    with psycopg.connect(phase7["dsn"]) as conn:
        dossiers = conn.execute("SELECT json_key, pdf_key FROM argos.dossiers").fetchall()
        credentials = conn.execute("SELECT count(*) FROM argos.credentials").fetchone()
    assert dossiers and credentials is not None and credentials[0] >= 1
    json_key, pdf_key = dossiers[-1]
    listed = _s3().list_object_versions(Bucket=EVIDENCE_BUCKET, Prefix=json_key.rsplit("/", 1)[0])
    keys = {v["Key"] for v in listed.get("Versions", [])}
    assert {json_key, pdf_key} <= keys
    assert (phase7["out"] / "dossier.pdf").read_bytes().startswith(b"%PDF")


def test_the_root_verifies_and_every_check_passes(phase7: dict[str, Any]) -> None:
    report = verify_bundle(phase7["bundle"], phase7["trust"])
    assert report.ok
    assert {c.status for c in report.checks} == {"passed"}
    names = {c.name for c in report.checks}
    assert {"root_signature", "root_matches_dossier", "timestamp", "credential"} <= names


@pytest.mark.parametrize(
    ("piece", "check"),
    [
        ("dossier", "dossier_hash"),
        ("root_signature", "root_signature"),
        ("timestamp_token", "timestamp"),
    ],
)
def test_a_corrupted_piece_is_named(phase7: dict[str, Any], piece: str, check: str) -> None:
    bundle = copy.deepcopy(phase7["bundle"])
    bundle[piece] = _flip(bundle[piece])
    assert check in _failed(bundle, phase7["trust"])


def test_a_corrupted_artifact_is_named_by_its_position(phase7: dict[str, Any]) -> None:
    for position in (0, len(phase7["bundle"]["artifacts"]) - 1):
        bundle = copy.deepcopy(phase7["bundle"])
        item = bundle["artifacts"][position]
        item["artifact"] = _flip(item["artifact"])
        assert _failed(bundle, phase7["trust"]) == [f"artifact_inclusion[{position}]"]


def test_the_worm_store_refuses_to_delete_or_overwrite_a_dossier(phase7: dict[str, Any]) -> None:
    with psycopg.connect(phase7["dsn"]) as conn:
        row = conn.execute("SELECT json_key, json_version_id FROM argos.dossiers").fetchone()
    assert row is not None
    s3 = _s3()
    with pytest.raises(ClientError):
        s3.delete_object(Bucket=EVIDENCE_BUCKET, Key=row[0], VersionId=row[1])
    with pytest.raises(ClientError):
        s3.put_object(Bucket=EVIDENCE_BUCKET, Key=row[0], Body=b"tampered", IfNoneMatch="*")
    kept = s3.get_object(Bucket=EVIDENCE_BUCKET, Key=row[0], VersionId=row[1])["Body"].read()
    assert kept == base64.b64decode(phase7["bundle"]["dossier"])


def test_the_public_verifier_container_verifies_and_a_revocation_is_seen(
    phase7: dict[str, Any],
) -> None:
    response = httpx.post(f"{VERIFIER}/verify", json=phase7["bundle"], timeout=60)
    assert response.json()["ok"] is True

    credential_id = phase7["bundle"]["credential"]["id"]
    revoke_credential(phase7["dsn"], credential_id, "prueba de la fase", "user:dpo")
    script = _script()
    activities = script.build_activities(
        script.get_config().model_copy(
            update={
                "DATABASE_URL": phase7["dsn"],
                "VAULT_TOKEN": script.SecretStr(script.DEV_VAULT_TOKEN),
            }
        ),
        script.EvidenceSettings(**script.DEV_EVIDENCE),
    )
    with psycopg.connect(phase7["dsn"]) as conn:
        row = conn.execute(
            "SELECT status_list FROM argos.credentials WHERE id = %s", (credential_id,)
        ).fetchone()
    assert row is not None
    revoked = copy.deepcopy(phase7["bundle"])
    revoked["status_list"] = activities.status_list(int(row[0]))
    report = httpx.post(f"{VERIFIER}/verify", json=revoked, timeout=60).json()
    failed = {c["name"]: c["detail"] for c in report["checks"] if c["status"] == "failed"}
    assert list(failed) == ["credential"]
    assert "revoked" in failed["credential"]
    assert revoked["credential"] == phase7["bundle"]["credential"]
