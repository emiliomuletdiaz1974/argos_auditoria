"""What a third party checks in an evidence bundle, piece by piece (ARG-069).

A bundle carries what was handed over (the dossier, the signed root envelope,
the time stamp token, the credential and some artifacts with their inclusion
proofs) and what is public (the issuer's DID document, the status list). Every
check has a name and says why it failed; a check that could not be made is
"skipped" and says so, never "passed".

What the bundle cannot bring is its own trust: whoever forges evidence can also
forge a DID document and a TSA. The keys of the issuers and the roots of the
time stamping authorities the verifier believes come from its own
configuration (`Trust`); without them nothing is verified.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography import x509

from argos_evidence.core.envelope import key_id, verify_envelope
from argos_evidence.core.integrity import file_digest, verify_artifact
from argos_evidence.core.timestamp import TimestampRejectedError, verify_reply
from argos_evidence.credential.multibase import public_key_from_multibase
from argos_evidence.credential.proof import verify_proof as verify_credential_proof
from argos_evidence.credential.verify import verify_credential
from argos_evidence.merkle import verify_proof

BUNDLE_SCHEMA = "argos/verification-bundle/1"
PASSED, FAILED, SKIPPED = "passed", "failed", "skipped"


@dataclass(frozen=True)
class Trust:
    """What this verifier believes, set by whoever runs it and never taken from a bundle."""

    issuer_key_ids: frozenset[str] = frozenset()
    tsa_roots_pem: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Trust:
        ids: Iterable[Any] = data.get("issuer_key_ids") or []
        roots: Iterable[Any] = data.get("tsa_roots_pem") or []
        return cls(frozenset(str(i) for i in ids), tuple(str(r) for r in roots))

    @classmethod
    def from_file(cls, path: str | Path | None) -> Trust:
        """The trust file of an installation; a missing file trusts nobody."""
        if not path or not Path(path).is_file():
            return cls()
        return cls.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.status != FAILED for c in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail} for c in self.checks
            ],
        }


def _bytes(bundle: Mapping[str, Any], name: str) -> bytes | None:
    value = bundle.get(name)
    if not isinstance(value, str):
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


def _guarded(report: Report, name: str, check: Callable[[], tuple[str, str]]) -> None:
    try:
        status, detail = check()
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        status, detail = FAILED, f"the bundle is malformed here: {type(exc).__name__}: {exc}"
    report.checks.append(Check(name, status, detail))


def _issuer_key(did_document: Any) -> bytes:
    methods = {m["id"]: m for m in did_document["verificationMethod"]}
    return public_key_from_multibase(
        methods[did_document["assertionMethod"][0]]["publicKeyMultibase"]
    )


def verify_bundle(
    bundle: Mapping[str, Any], trust: Trust, *, at: dt.datetime | None = None
) -> Report:
    """Check a bundle against what `trust` believes, as of `at` (now by default)."""
    at = at or dt.datetime.now(dt.UTC)
    report = Report()
    dossier_bytes = _bytes(bundle, "dossier")
    envelope = _bytes(bundle, "root_signature")
    dossier: dict[str, Any] = {}
    chain: dict[str, Any] = {}
    key: bytes | None = None

    def dossier_hash() -> tuple[str, str]:
        nonlocal dossier, chain
        if dossier_bytes is None:
            return FAILED, "the bundle has no readable dossier"
        if not verify_artifact(dossier_bytes):
            return FAILED, "the dossier does not match its own SHA-256: it was changed"
        dossier = json.loads(dossier_bytes)
        chain = dossier.get("evidence_chain") or {}
        return PASSED, f"dossier SHA-256 {file_digest(dossier_bytes)}"

    def issuer_key() -> tuple[str, str]:
        nonlocal key
        if not trust.issuer_key_ids:
            return FAILED, "the issuer is not anchored: this verifier trusts no issuer key yet"
        stated = _issuer_key(bundle["did_document"])
        if key_id(stated) not in trust.issuer_key_ids:
            return FAILED, f"the issuer key {key_id(stated)} is not one this verifier trusts"
        key = stated
        return PASSED, f"key {key_id(stated)} of {bundle['did_document']['id']}, trusted"

    def root_signature() -> tuple[str, str]:
        if key is None or envelope is None:
            return FAILED, "there is no signed root or no issuer key to check it with"
        if not verify_envelope(envelope, key):
            return FAILED, "the signature of the campaign root does not verify with the issuer key"
        payload = json.loads(envelope)["payload"]
        note = " (development key, not production)" if payload.get("non_production") else ""
        return PASSED, f"root signed by key {payload['key_id']}{note}"

    def root_matches_dossier() -> tuple[str, str]:
        if envelope is None or not chain:
            return FAILED, "there is no signed root or no dossier to compare"
        payload = json.loads(envelope)["payload"]
        if payload["merkle_root"] != (chain.get("merkle") or {}).get("root"):
            return FAILED, "the signed Merkle root is not the one the dossier states"
        if payload["campaign_id"] != dossier["campaign"]["id"]:
            return FAILED, "the signed root belongs to another campaign"
        if file_digest(envelope) != (chain.get("signature") or {}).get("sha256"):
            return FAILED, "the dossier cites another signature envelope"
        return PASSED, "the dossier, the signature and the Merkle root agree"

    def timestamp() -> tuple[str, str]:
        token = _bytes(bundle, "timestamp_token")
        stated = (chain.get("time_stamp") or {}).get("status")
        if token is None:
            if stated == "stamped":
                return FAILED, "the dossier says the root is stamped but no token was given"
            return SKIPPED, "the root is signed; its time stamp is still queued"
        if envelope is None:
            return FAILED, "there is no signed root for the token to cover"
        if not trust.tsa_roots_pem:
            return FAILED, "no trusted TSA root is configured to check the token against"
        roots = [x509.load_pem_x509_certificate(p.encode()) for p in trust.tsa_roots_pem]
        try:
            info = verify_reply(token, envelope, None, roots).tst_info
        except TimestampRejectedError as exc:
            return FAILED, f"the time stamp token does not verify: {exc}"
        return (
            PASSED,
            f"stamped at {info.gen_time.isoformat()} under policy {info.policy.dotted_string}",
        )

    def credential() -> tuple[str, str]:
        if bundle.get("credential") is None:
            return SKIPPED, "no credential was given"
        if key is None:
            return FAILED, "the credential cannot be checked without a trusted issuer key"
        check = verify_credential(
            bundle["credential"], bundle["did_document"], bundle.get("status_list"), at=at
        )
        if not check.valid:
            return FAILED, "the credential does not verify: " + ", ".join(check.reasons)
        return PASSED, "the credential verifies against the issuer DID and is not revoked"

    def credential_matches_dossier() -> tuple[str, str]:
        if bundle.get("credential") is None:
            return SKIPPED, "no credential was given"
        stated = bundle["credential"]["credentialSubject"]["dossierSha256"]
        if dossier_bytes is None or stated != file_digest(dossier_bytes):
            return FAILED, "the credential vouches for another dossier"
        return PASSED, "the credential vouches for this dossier"

    def dossier_authenticated() -> tuple[str, str]:
        # The dossier's own SHA-256 only says it is whole; who stands behind what it says is the
        # credential, signed by the issuer over that SHA-256. Revoked or not, the signature holds.
        document = bundle.get("credential")
        if document is None:
            return FAILED, "nothing signed vouches for the content of this dossier: no credential"
        if key is None or document.get("issuer") != bundle["did_document"]["id"]:
            return FAILED, "the credential is not from a trusted issuer"
        if not verify_credential_proof(document, key):
            return FAILED, "the signature over the dossier does not verify"
        stated = document["credentialSubject"]["dossierSha256"]
        if dossier_bytes is None or stated != file_digest(dossier_bytes):
            return FAILED, "the signed statement is about another dossier"
        return PASSED, "the content of the dossier is vouched for by the issuer's signature"

    for name, step in (
        ("dossier_hash", dossier_hash),
        ("issuer_key", issuer_key),
        ("root_signature", root_signature),
        ("root_matches_dossier", root_matches_dossier),
        ("timestamp", timestamp),
        ("credential", credential),
        ("credential_matches_dossier", credential_matches_dossier),
        ("dossier_authenticated", dossier_authenticated),
    ):
        _guarded(report, name, step)

    root = (chain.get("merkle") or {}).get("root")
    try:
        signed_leaves = int(json.loads(envelope or b"{}")["payload"]["leaf_count"])
    except (KeyError, TypeError, ValueError):
        signed_leaves = None
    for position, item in enumerate(bundle.get("artifacts") or []):

        def inclusion(item: Mapping[str, Any] = item) -> tuple[str, str]:
            artifact = _bytes(item, "artifact")
            if artifact is None or not verify_artifact(artifact):
                return FAILED, "the artifact does not match its own SHA-256: it was changed"
            path = [(str(side), bytes.fromhex(sibling)) for side, sibling in item["proof"]["path"]]
            digest = hashlib.sha256(artifact).digest()
            if item["proof"]["root"] != root:
                return FAILED, "the proof leads to another root than the dossier's"
            index, size = int(item["proof"]["index"]), int(item["proof"]["size"])
            if size != signed_leaves:
                return (
                    FAILED,
                    f"the proof is for a tree of {size}, the signed root has {signed_leaves}",
                )
            if not verify_proof(digest, index, size, path, bytes.fromhex(root)):
                return FAILED, f"the artifact is not leaf {index} of the campaign tree"
            return PASSED, f"leaf {index} of {size}"

        _guarded(report, f"artifact_inclusion[{position}]", inclusion)
    return report
