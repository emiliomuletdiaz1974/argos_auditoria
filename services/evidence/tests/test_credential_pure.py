"""ARG-068 · did:web, Bitstring Status List and a credential with nothing personal in it."""

import copy
import gzip
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from argos_evidence.artifacts import personal_identifiers
from argos_evidence.credential.did import did_document, did_web, did_web_url, verification_method
from argos_evidence.credential.issue import (
    SUBJECT_KEYS,
    build_credential,
    credential_subject,
    status_list_credential_document,
    verify_credential,
)
from argos_evidence.credential.multibase import multibase_decode
from argos_evidence.credential.proof import add_proof
from argos_evidence.credential.status import (
    LIST_SIZE,
    decode_list,
    encode_list,
    is_set,
    new_bitstring,
    set_bit,
)

DID = did_web("evidence.argos.example")
LIST_URL = "https://evidence.argos.example/status/0"


class LocalSigner:
    def __init__(self) -> None:
        self._key = Ed25519PrivateKey.generate()

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _dossier(name: str = "Campaña de demostración") -> dict[str, Any]:
    return {
        "campaign": {
            "id": "0199a000-0000-7000-8000-000000000001",
            "name": name,
            "sealed_at": "2026-09-18T10:00:00.000000Z",
            "library_version": "1.0.0",
            "ontology_version": "1.0.0",
        },
        "results": {
            "units": 3,
            "by_result": {
                "compliant": 2,
                "non_compliant": 1,
                "not_demonstrated": 0,
                "inconclusive": 0,
            },
        },
        "findings": [{"severity": "high", "challenge_id": "sec-tls", "id": "f"}],
        "evidence_chain": {
            "merkle": {"root": "r" * 64},
            "signature": {"non_production": True},
        },
    }


def _issued(signer: LocalSigner, index: int = 7) -> dict[str, Any]:
    document = build_credential(
        credential_id="urn:uuid:0199a000-0000-7000-8000-00000000000c",
        issuer=DID,
        valid_from="2026-09-18T10:05:00Z",
        subject=credential_subject(_dossier(), "d" * 64),
        status_list_url=LIST_URL,
        status_index=index,
    )
    return add_proof(document, signer, verification_method(DID), "2026-09-18T10:05:00Z")


def _status_list(signer: LocalSigner, revoked: set[int]) -> dict[str, Any]:
    document = status_list_credential_document(DID, LIST_URL, revoked, "2026-09-18T10:06:00Z")
    return add_proof(document, signer, verification_method(DID), "2026-09-18T10:06:00Z")


def test_did_web_names_and_urls() -> None:
    assert DID == "did:web:evidence.argos.example"
    assert did_web("localhost:3190") == "did:web:localhost%3A3190"
    assert did_web_url(DID) == "https://evidence.argos.example/.well-known/did.json"
    assert did_web_url("did:web:localhost%3A3190") == "https://localhost:3190/.well-known/did.json"


def test_the_did_document_publishes_the_key_for_assertions() -> None:
    signer = LocalSigner()
    document = did_document(DID, signer.public_key())
    method = document["verificationMethod"][0]
    assert method["id"] == verification_method(DID)
    assert method["type"] == "Multikey"
    assert method["controller"] == DID
    assert multibase_decode(method["publicKeyMultibase"])[2:] == signer.public_key()
    assert document["assertionMethod"] == [method["id"]]


def test_the_bitstring_is_msb_first_gzip_and_base64url_multibase() -> None:
    bits = new_bitstring()
    assert len(bits) * 8 == LIST_SIZE == 131072
    set_bit(bits, 0)
    set_bit(bits, 9)
    assert bits[0] == 0b1000_0000 and bits[1] == 0b0100_0000
    encoded = encode_list(bits)
    assert encoded.startswith("u") and "=" not in encoded
    assert encode_list(bits) == encoded
    assert decode_list(encoded) == bits
    assert is_set(bits, 9) and not is_set(bits, 8)
    assert gzip.decompress(multibase_decode(encoded)) == bytes(bits)


def test_the_subject_says_what_was_verified_and_nothing_personal() -> None:
    subject = credential_subject(_dossier("Paciente 12345678Z"), "d" * 64)
    assert set(subject) <= SUBJECT_KEYS
    assert subject["dossierSha256"] == "d" * 64
    assert subject["merkleRoot"] == "r" * 64
    assert subject["results"] == {
        "compliant": 2,
        "non_compliant": 1,
        "not_demonstrated": 0,
        "inconclusive": 0,
    }
    assert subject["findingsBySeverity"] == {"high": 1}
    assert subject["nonProduction"] is True
    assert personal_identifiers(subject) == []
    assert "Paciente" not in str(subject)


def test_an_issued_credential_verifies_against_its_did_and_status_list() -> None:
    signer = LocalSigner()
    credential = _issued(signer)
    check = verify_credential(
        credential, did_document(DID, signer.public_key()), _status_list(signer, set())
    )
    assert check.valid, check.reasons


def test_revoking_is_flipping_a_bit_in_the_list_not_touching_the_credential() -> None:
    signer = LocalSigner()
    credential = _issued(signer, index=7)
    before = copy.deepcopy(credential)
    check = verify_credential(
        credential, did_document(DID, signer.public_key()), _status_list(signer, {7})
    )
    assert not check.valid and "revoked" in check.reasons
    assert credential == before


def test_a_credential_without_its_status_list_is_not_declared_valid() -> None:
    signer = LocalSigner()
    check = verify_credential(_issued(signer), did_document(DID, signer.public_key()), None)
    assert not check.valid and "status not checked" in check.reasons


def test_another_issuer_key_or_a_forged_status_list_is_rejected() -> None:
    signer, other = LocalSigner(), LocalSigner()
    credential = _issued(signer)
    wrong_did = verify_credential(
        credential, did_document(DID, other.public_key()), _status_list(signer, set())
    )
    assert not wrong_did.valid and "proof" in wrong_did.reasons
    forged = verify_credential(
        credential, did_document(DID, signer.public_key()), _status_list(other, set())
    )
    assert not forged.valid and "status list proof" in forged.reasons
