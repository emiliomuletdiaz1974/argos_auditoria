"""ARG-010 · manifest signed with Vault transit and verified offline."""

import os

import hvac
import pytest

from argos_common.errors import IntegrityError
from argos_common.release import (
    VaultTransitSigner,
    build_manifest,
    serialize,
    verify_signature,
)

pytestmark = pytest.mark.integration
VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")


def test_signed_in_vault_and_verified_offline() -> None:
    signer = VaultTransitSigner(VAULT, "root")
    data = serialize(
        build_manifest(
            "0.1.0",
            [{"ref": "argos-example:0.1.0@sha256:" + "c" * 64, "component": "ARG-001"}],
            None,
            "2026-09-14T10:00:00Z",
        )
    )
    signature = signer.sign(data)
    public_key = signer.public_key()
    verify_signature(data, signature, public_key)
    with pytest.raises(IntegrityError):
        verify_signature(data + b" ", signature, public_key)


def test_private_key_is_not_exportable() -> None:
    info = hvac.Client(url=VAULT, token="root").secrets.transit.read_key(name="argos-release")
    assert info["data"]["exportable"] is False
    assert info["data"]["type"] == "ed25519"
