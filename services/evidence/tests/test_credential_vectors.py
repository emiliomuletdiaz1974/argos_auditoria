"""ARG-068 · eddsa-jcs-2022 byte for byte against the W3C test vectors (vc-di-eddsa, B.3)."""

import copy
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from argos_evidence.credential.multibase import (
    multibase_decode,
    public_key_from_multibase,
    public_key_multibase,
)
from argos_evidence.credential.proof import add_proof, hash_data, jcs, verify_proof

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parents[3] / "tests" / "vectors" / "vc_eddsa_jcs_2022.json").read_text(
        encoding="utf-8"
    )
)
ED25519_PRIVATE = b"\x80\x26"


class VectorSigner:
    """The W3C test key: never used outside these vectors."""

    def __init__(self) -> None:
        raw = multibase_decode(VECTORS["secret_key_multibase"])
        assert raw[:2] == ED25519_PRIVATE
        self._key = Ed25519PrivateKey.from_private_bytes(raw[2:])

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _options() -> dict[str, Any]:
    return dict(VECTORS["proof_options"])


def test_the_public_key_round_trips_through_multikey() -> None:
    signer = VectorSigner()
    assert public_key_multibase(signer.public_key()) == VECTORS["public_key_multibase"]
    assert public_key_from_multibase(VECTORS["public_key_multibase"]) == signer.public_key()


def test_the_document_and_the_proof_options_canonicalise_as_rfc_8785() -> None:
    assert jcs(VECTORS["unsecured_document"]).decode() == VECTORS["canonical_document"]
    assert jcs(_options()).decode() == VECTORS["canonical_proof_options"]


def test_the_hash_data_is_the_proof_options_hash_then_the_document_hash() -> None:
    data = hash_data(VECTORS["unsecured_document"], _options())
    assert data.hex() == VECTORS["hash_data"]
    assert data[:32].hex() == VECTORS["proof_options_hash"]
    assert data[32:].hex() == VECTORS["document_hash"]


def test_the_signature_and_the_signed_document_are_the_published_ones() -> None:
    options = _options()
    options.pop("@context")
    signed = add_proof(
        VECTORS["unsecured_document"],
        VectorSigner(),
        verification_method=options["verificationMethod"],
        created=options["created"],
    )
    assert signed == VECTORS["signed_document"]
    assert signed["proof"]["proofValue"] == VECTORS["proof_value"]


def test_the_published_credential_verifies_and_any_change_does_not() -> None:
    public_key = VectorSigner().public_key()
    assert verify_proof(VECTORS["signed_document"], public_key)
    for path in (("name",), ("credentialSubject", "alumniOf"), ("proof", "created")):
        tampered = copy.deepcopy(VECTORS["signed_document"])
        target = tampered
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = target[path[-1]] + "x"
        assert not verify_proof(tampered, public_key), path
