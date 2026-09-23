"""ARG-069 · the public verifier: an intact bundle passes, each altered piece fails by name."""

import base64
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from argos_evidence.core.envelope import key_id
from argos_evidence.core.integrity import file_digest, seal_document
from argos_evidence.credential.did import did_document, did_web, did_web_url, verification_method
from argos_evidence.credential.issue import (
    build_credential,
    credential_subject,
    status_list_credential_document,
)
from argos_evidence.credential.multibase import base64url_multibase, public_key_from_multibase
from argos_evidence.credential.proof import add_proof
from argos_evidence.credential.status import decode_list
from argos_evidence.merkle import build_tree, proof
from argos_verifier.api import MAX_BUNDLE_BYTES, app
from argos_verifier.checks import Trust, verify_bundle

DID = did_web("evidence.argos.example")
LIST_URL = "https://evidence.argos.example/status/0"
CAMPAIGN = "0199a000-0000-7000-8000-000000000001"
TOOL = Path(__file__).parents[3] / "tools" / "verify_evidence.py"


class LocalSigner:
    def __init__(self) -> None:
        self._key = Ed25519PrivateKey.generate()

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


SIGNER = LocalSigner()
TRUST = Trust(issuer_key_ids=frozenset({key_id(SIGNER.public_key())}))
NOW = dt.datetime(2026, 9, 18, 12, 0, tzinfo=dt.UTC)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _envelope(signer: LocalSigner, root: str) -> bytes:
    payload = {
        "schema": "argos/root-signature/1",
        "kind": "campaign_root_signature",
        "campaign_id": CAMPAIGN,
        "merkle_root": root,
        "leaf_count": 3,
        "key_id": key_id(signer.public_key()),
        "non_production": True,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    envelope = {
        "payload": payload,
        "signature": signer.sign(body).hex(),
        "public_key": signer.public_key().hex(),
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()


def _bundle(revoked: bool = False, signer: LocalSigner = SIGNER) -> dict[str, Any]:
    artifacts = [seal_document({"schema": "argos/evidence/1", "verdict": i}) for i in range(3)]
    tree = build_tree([hashlib.sha256(a).digest() for a in artifacts])
    envelope = _envelope(signer, tree.root.hex())
    dossier = seal_document(
        {
            "schema": "argos/dossier/1",
            "campaign": {"id": CAMPAIGN, "sealed_at": "2026-09-18T10:00:00.000000Z"},
            "results": {"units": 3, "by_result": {"compliant": 3}},
            "findings": [],
            "evidence_chain": {
                "merkle": {"root": tree.root.hex(), "leaf_count": 3},
                "signature": {"sha256": file_digest(envelope), "non_production": True},
                "time_stamp": {"status": "queued"},
            },
        }
    )
    credential = add_proof(
        build_credential(
            credential_id="urn:uuid:0199a000-0000-7000-8000-00000000000c",
            issuer=DID,
            valid_from="2026-09-18T10:05:00Z",
            subject=credential_subject(json.loads(dossier), file_digest(dossier)),
            status_list_url=LIST_URL,
            status_index=5,
        ),
        signer,
        verification_method(DID),
        "2026-09-18T10:05:00Z",
    )
    status_list = add_proof(
        status_list_credential_document(
            DID,
            LIST_URL,
            {5} if revoked else set(),
            "2026-09-18T10:06:00Z",
            valid_until="2026-09-19T10:06:00Z",
        ),
        signer,
        verification_method(DID),
        "2026-09-18T10:06:00Z",
    )
    return {
        "schema": "argos/verification-bundle/1",
        "dossier": _b64(dossier),
        "root_signature": _b64(envelope),
        "timestamp_token": None,
        "tsa_roots": [],
        "did_document": did_document(DID, signer.public_key()),
        "credential": credential,
        "status_list": status_list,
        "artifacts": [
            {
                "artifact": _b64(artifact),
                "proof": {
                    "index": i,
                    "size": tree.size,
                    "path": [[side, sibling.hex()] for side, sibling in proof(tree, i)],
                    "root": tree.root.hex(),
                },
            }
            for i, artifact in enumerate(artifacts)
        ],
    }


def _verify(bundle: dict[str, Any], trust: Trust = TRUST) -> Any:
    return verify_bundle(bundle, trust, at=NOW)


def _failed(bundle: dict[str, Any], trust: Trust = TRUST) -> set[str]:
    return {c.name for c in _verify(bundle, trust).checks if c.status == "failed"}


def _flip(encoded: str) -> str:
    data = bytearray(base64.b64decode(encoded))
    data[len(data) // 2] ^= 0x01
    return _b64(bytes(data))


def test_an_intact_bundle_passes_and_says_what_it_did_not_check() -> None:
    report = _verify(_bundle())
    assert report.ok, [c for c in report.checks if c.status == "failed"]
    statuses = {c.name: c.status for c in report.checks}
    assert statuses["timestamp"] == "skipped"
    assert statuses["dossier_hash"] == statuses["root_signature"] == "passed"
    assert statuses["artifact_inclusion[2]"] == "passed"


@pytest.mark.parametrize(
    ("piece", "expected"),
    [
        ("dossier", "dossier_hash"),
        ("root_signature", "root_signature"),
    ],
)
def test_a_changed_byte_fails_the_check_of_that_piece(piece: str, expected: str) -> None:
    bundle = _bundle()
    bundle[piece] = _flip(bundle[piece])
    assert expected in _failed(bundle)


def test_a_changed_artifact_or_proof_fails_its_inclusion() -> None:
    bundle = _bundle()
    bundle["artifacts"][1]["artifact"] = _flip(bundle["artifacts"][1]["artifact"])
    assert _failed(bundle) == {"artifact_inclusion[1]"}
    bundle = _bundle()
    bundle["artifacts"][0]["proof"]["path"][0][1] = "00" * 32
    assert _failed(bundle) == {"artifact_inclusion[0]"}


def test_a_root_signed_for_another_tree_does_not_match_the_dossier() -> None:
    bundle = _bundle()
    other = _bundle(signer=LocalSigner())  # Ed25519 is deterministic: same key, same envelope
    bundle["root_signature"] = other["root_signature"]
    bundle["did_document"] = other["did_document"]
    assert "root_matches_dossier" in _failed(bundle)


def test_a_revoked_credential_fails_and_says_so() -> None:
    report = _verify(_bundle(revoked=True))
    failed = [c for c in report.checks if c.status == "failed"]
    assert [c.name for c in failed] == ["credential"]
    assert "revoked" in failed[0].detail


def test_a_credential_for_another_dossier_is_caught() -> None:
    bundle = _bundle()
    bundle["credential"] = _bundle(signer=LocalSigner())["credential"]
    assert "credential_matches_dossier" in _failed(bundle)


def test_a_malformed_bundle_is_a_failed_check_not_a_crash() -> None:
    report = _verify({"schema": "argos/verification-bundle/1"})
    assert not report.ok
    assert {c.name for c in report.checks if c.status == "failed"} >= {"dossier_hash"}


def test_the_cli_and_the_api_give_the_same_report(tmp_path: Path) -> None:
    bundle = _bundle(revoked=True)
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("verify_evidence", TOOL)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert tool.main([str(path), "--json", str(tmp_path / "report.json")]) == 1
    from_cli = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    response = TestClient(app).post("/verify", json=bundle)
    assert response.status_code == 200
    assert response.json() == from_cli
    assert from_cli["ok"] is False


def test_the_api_refuses_an_oversized_bundle() -> None:
    body = b"{" + b" " * (MAX_BUNDLE_BYTES + 1) + b"}"
    response = TestClient(app).post(
        "/verify", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


# ---------- hardening from the security review (F09-02, F09-20) ----------


def test_a_bundle_signed_by_a_key_nobody_trusts_is_not_verified() -> None:
    """SEC-001: the issuer key comes from the verifier's trust, never from the bundle."""
    forged = _bundle(signer=LocalSigner())
    report = _verify(forged)
    assert not report.ok
    assert "issuer_key" in _failed(forged)


def test_without_trust_anchors_nothing_is_verified() -> None:
    report = verify_bundle(_bundle(), Trust(), at=NOW)
    assert not report.ok
    detail = next(c.detail for c in report.checks if c.name == "issuer_key")
    assert "not anchored" in detail


def test_the_tsa_roots_of_the_bundle_are_not_trusted() -> None:
    bundle = _bundle()
    bundle["timestamp_token"] = _b64(b"not a token")
    bundle["tsa_roots"] = ["-----BEGIN CERTIFICATE-----\nnot trusted\n-----END CERTIFICATE-----"]
    assert "timestamp" in _failed(bundle)
    detail = next(c.detail for c in _verify(bundle).checks if c.name == "timestamp")
    assert "trusted TSA" in detail


def test_a_dossier_rewritten_without_its_credential_is_not_verified() -> None:
    """SEC-002: only something signed vouches for what the dossier says."""
    bundle = _bundle()
    dossier = json.loads(base64.b64decode(bundle["dossier"]))
    dossier["results"]["by_result"] = {"compliant": 99}
    dossier.pop("sha256", None)
    bundle["dossier"] = _b64(seal_document({k: v for k, v in dossier.items()}))
    bundle["credential"] = None
    assert "dossier_authenticated" in _failed(bundle)
    assert not _verify(bundle).ok


def test_an_expired_status_list_does_not_prove_non_revocation() -> None:
    """SEC-018: a list kept from before a revocation stops counting when it expires."""
    report = verify_bundle(_bundle(), TRUST, at=NOW + dt.timedelta(days=2))
    failed = {c.name: c.detail for c in report.checks if c.status == "failed"}
    assert "credential" in failed
    assert "status list expired" in failed["credential"]


def test_a_proof_for_another_tree_size_is_refused() -> None:
    """SEC-039: the size of the proof is the leaf count the signed root states."""
    bundle = _bundle()
    bundle["artifacts"][2]["proof"]["size"] = 2
    bundle["artifacts"][2]["proof"]["index"] = 1
    assert "artifact_inclusion[2]" in _failed(bundle)


def test_an_enormous_multibase_value_is_refused_at_once() -> None:
    """SEC-003: base58 decoding is quadratic; the length is checked before decoding."""
    started = time.perf_counter()
    with pytest.raises(ValueError):
        public_key_from_multibase("z" + "2" * 200_000)
    assert time.perf_counter() - started < 0.5


def test_a_gzip_bomb_in_the_status_list_is_refused() -> None:
    bomb = gzip.compress(bytes(4 * 1024 * 1024), mtime=0)
    with pytest.raises(ValueError):
        decode_list(base64url_multibase(bomb))


def test_a_chunked_body_larger_than_the_limit_is_refused() -> None:
    def chunks() -> Any:
        for _ in range(MAX_BUNDLE_BYTES // (1024 * 1024) + 2):
            yield b" " * (1024 * 1024)

    response = TestClient(app).post(
        "/verify", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    "did",
    [
        "did:web:evidence.argos.example%40evil.com",
        "did:web:evidence.argos.example%2Fevil",
        "did:web:evidence.argos.example%3Fx",
        "did:web:evidence.argos.example%23x",
    ],
)
def test_a_did_web_that_leaves_its_host_is_refused(did: str) -> None:
    """SEC-038."""
    with pytest.raises(ValueError):
        did_web_url(did)


def test_a_did_web_with_a_port_still_resolves() -> None:
    assert did_web_url("did:web:localhost%3A8008") == "https://localhost:8008/.well-known/did.json"
