"""Data Integrity proofs with the eddsa-jcs-2022 cryptosuite (ARG-068, ADR-0011).

Canonical form is JCS (RFC 8785) through the ``rfc8785`` package, not the
journal's canonicalisation: they coincide for the data ARGOS writes but not in
general, and a verifier outside ARGOS applies the RFC. The data signed is
SHA-256(JCS(proof options)) followed by SHA-256(JCS(document without proof)).
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from argos_common.release import Signer
from argos_evidence.credential.multibase import base58btc_encode, multibase_decode

CRYPTOSUITE = "eddsa-jcs-2022"
PROOF_TYPE = "DataIntegrityProof"


def jcs(value: Any) -> bytes:
    return rfc8785.dumps(value)


def hash_data(document: Mapping[str, Any], proof_options: Mapping[str, Any]) -> bytes:
    return (
        hashlib.sha256(jcs(dict(proof_options))).digest()
        + hashlib.sha256(jcs(dict(document))).digest()
    )


def add_proof(
    document: Mapping[str, Any],
    signer: Signer,
    verification_method: str,
    created: str,
    proof_purpose: str = "assertionMethod",
) -> dict[str, Any]:
    """The document with an eddsa-jcs-2022 proof by ``signer`` attached."""
    unsecured = {k: copy.deepcopy(v) for k, v in document.items() if k != "proof"}
    options: dict[str, Any] = {
        "type": PROOF_TYPE,
        "cryptosuite": CRYPTOSUITE,
        "created": created,
        "verificationMethod": verification_method,
        "proofPurpose": proof_purpose,
    }
    if "@context" in unsecured:
        options["@context"] = copy.deepcopy(unsecured["@context"])
    signature = signer.sign(hash_data(unsecured, options))
    return {**unsecured, "proof": {**options, "proofValue": "z" + base58btc_encode(signature)}}


def verify_proof(
    secured: Mapping[str, Any], public_key: bytes, proof_purpose: str = "assertionMethod"
) -> bool:
    """True when the eddsa-jcs-2022 proof of ``secured`` was made with ``public_key``."""
    try:
        proof = dict(secured["proof"])
        if proof.get("type") != PROOF_TYPE or proof.get("cryptosuite") != CRYPTOSUITE:
            return False
        if proof.get("proofPurpose") != proof_purpose:
            return False
        signature = multibase_decode(str(proof.pop("proofValue")))
        unsecured = {k: v for k, v in secured.items() if k != "proof"}
        if "@context" in proof:
            context = unsecured.get("@context")
            if not isinstance(context, list) or context[: len(proof["@context"])] != list(
                proof["@context"]
            ):
                return False
            unsecured["@context"] = proof["@context"]
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, hash_data(unsecured, proof)
        )
    except (KeyError, TypeError, ValueError, InvalidSignature):
        return False
    return True
