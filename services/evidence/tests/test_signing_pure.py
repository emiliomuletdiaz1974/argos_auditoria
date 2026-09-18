"""ARG-064 · the signed object of a campaign root: canonical, verifiable, honest about its key."""

import datetime as dt
import json
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from argos_evidence.signing import (
    ALGORITHM,
    envelope_bytes,
    key_id,
    sign_payload,
    signing_payload,
    verify_envelope,
)

CAMPAIGN = "0199a000-0000-7000-8000-000000000001"
HEAD = {"seq": 118, "entry_hash": "e" * 64}
AT = dt.datetime(2026, 9, 18, 10, 0, 0, tzinfo=dt.UTC)


class LocalSigner:
    def __init__(self, production: bool = False) -> None:
        self._key = Ed25519PrivateKey.generate()
        if production:
            self.production = True

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _payload(signer: Any, **overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "campaign_id": CAMPAIGN,
        "merkle_root": "r" * 64,
        "leaf_count": 7,
        "leaf_order": "verdict_id",
        "tree_key": f"campaigns/{CAMPAIGN}/merkle-tree.json",
        "campaign_seal": "s" * 64,
        "journal_head": HEAD,
        "signed_at": AT,
        "signer": signer,
    }
    arguments.update(overrides)
    return signing_payload(**arguments)


def test_the_payload_is_stable_and_says_what_it_covers() -> None:
    signer = LocalSigner()
    payload = _payload(signer)
    assert payload == _payload(signer)
    assert payload["algorithm"] == ALGORITHM == "Ed25519"
    assert payload["key_id"] == key_id(signer.public_key())
    assert payload["signed_at"] == "2026-09-18T10:00:00.000000Z"
    assert payload["journal_head"] == HEAD
    assert payload["campaign_seal"] == "s" * 64


def test_a_signer_that_is_not_declared_production_marks_every_object() -> None:
    assert _payload(LocalSigner())["non_production"] is True
    assert _payload(LocalSigner(production=True))["non_production"] is False


def test_the_envelope_verifies_with_the_public_key() -> None:
    signer = LocalSigner()
    body = envelope_bytes(sign_payload(signer, _payload(signer)))
    assert verify_envelope(body, signer.public_key())


def test_changing_any_field_of_the_payload_breaks_the_signature() -> None:
    signer = LocalSigner()
    body = envelope_bytes(sign_payload(signer, _payload(signer)))
    envelope = json.loads(body)
    for field, value in envelope["payload"].items():
        altered = json.loads(body)
        altered["payload"][field] = (
            not value if isinstance(value, bool) else (value + 1 if isinstance(value, int) else "x")
        )
        tampered = json.dumps(altered, sort_keys=True, separators=(",", ":")).encode()
        assert not verify_envelope(tampered, signer.public_key()), field


def test_another_key_does_not_verify() -> None:
    signer = LocalSigner()
    body = envelope_bytes(sign_payload(signer, _payload(signer)))
    assert not verify_envelope(body, LocalSigner().public_key())


def test_a_malformed_envelope_is_rejected_not_raised() -> None:
    signer = LocalSigner()
    assert not verify_envelope(b"{}", signer.public_key())
    assert not verify_envelope(b"not json", signer.public_key())


def test_the_signed_time_must_carry_a_time_zone() -> None:
    with pytest.raises(ValueError, match="time zone"):
        _payload(LocalSigner(), signed_at=dt.datetime(2026, 9, 18, 10))  # noqa: DTZ001


def test_the_journal_head_is_required() -> None:
    with pytest.raises(ValueError, match="journal head"):
        _payload(LocalSigner(), journal_head={"seq": 1})
