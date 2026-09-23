"""Verification of a campaign credential against its issuer's DID and status list (ARG-068).

Part of the pure verification core: no database, no store, no network.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from argos_evidence.credential.multibase import public_key_from_multibase
from argos_evidence.credential.proof import verify_proof
from argos_evidence.credential.status import decode_list, is_set


@dataclass
class CredentialCheck:
    reasons: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.reasons


def _issuer_key(
    document: Mapping[str, Any], did_document: Mapping[str, Any], check: CredentialCheck
) -> bytes | None:
    issuer = document.get("issuer")
    method_id = (document.get("proof") or {}).get("verificationMethod")
    if did_document.get("id") != issuer:
        check.reasons.append("issuer")
        return None
    methods = {m.get("id"): m for m in did_document.get("verificationMethod", [])}
    method = methods.get(method_id)
    if (
        method is None
        or method_id not in did_document.get("assertionMethod", [])
        or method.get("controller") != issuer
    ):
        check.reasons.append("verification method")
        return None
    try:
        return public_key_from_multibase(str(method["publicKeyMultibase"]))
    except (KeyError, ValueError):
        check.reasons.append("verification method")
        return None


def verify_credential(
    credential: Mapping[str, Any],
    did_document: Mapping[str, Any],
    status_list: Mapping[str, Any] | None,
    *,
    at: dt.datetime | None = None,
) -> CredentialCheck:
    """Check the proof against the issuer's DID and the revocation bit in its status list.

    A status list only says "not revoked" until it expires: one kept from before a revocation
    stops counting at its `validUntil` (as of `at`, now by default).
    """
    check = CredentialCheck()
    key = _issuer_key(credential, did_document, check)
    if key is not None and not verify_proof(credential, key):
        check.reasons.append("proof")
    status = credential.get("credentialStatus")
    if status is None:
        return check
    if status_list is None:
        check.reasons.append("status not checked")
        return check
    list_check = CredentialCheck()
    list_key = _issuer_key(status_list, did_document, list_check)
    if list_key is None or not verify_proof(status_list, list_key):
        check.reasons.append("status list proof")
        return check
    expiry = status_list.get("validUntil")
    try:
        until = dt.datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
    except ValueError:
        check.reasons.append("status list without expiry")
        return check
    if (at or dt.datetime.now(dt.UTC)) > until:
        check.reasons.append("status list expired")
        return check
    subject = status_list.get("credentialSubject") or {}
    if status_list.get("id") != status.get("statusListCredential") or subject.get(
        "statusPurpose"
    ) != status.get("statusPurpose"):
        check.reasons.append("status list mismatch")
        return check
    try:
        revoked = is_set(decode_list(str(subject["encodedList"])), int(status["statusListIndex"]))
    except (KeyError, ValueError, IndexError, OSError):
        check.reasons.append("status list mismatch")
        return check
    if revoked:
        check.reasons.append("revoked")
    return check
