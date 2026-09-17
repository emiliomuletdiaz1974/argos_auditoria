"""ARG-040 · bundles signed with the Vault content key load only when verified."""

import os
from datetime import date

import hvac
import psycopg
import pytest

from argos_common.release import VaultTransitSigner
from argos_ontology.bundle import (
    CONTENT_KEY,
    BundleRejectedError,
    build_bundle,
    load_bundle,
    sign_bundle,
)
from argos_ontology.store import OntologyStore
from argos_ontology.vocabulary import LIBRARY_DIR

pytestmark = pytest.mark.integration
VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")
KEY = os.environ.get("ARGOS_TEST_CONTENT_KEY", CONTENT_KEY)


def test_the_content_key_is_ed25519_and_not_exportable() -> None:
    info = hvac.Client(url=VAULT, token="root").secrets.transit.read_key(name=KEY)
    assert info["data"]["type"] == "ed25519"
    assert info["data"]["exportable"] is False


def test_a_vault_signed_bundle_is_verified_and_loaded(migrated_db: str) -> None:
    signer = VaultTransitSigner(VAULT, "root", key=KEY)
    bundle, manifest = build_bundle(LIBRARY_DIR, "1.0.0", date(2026, 10, 1))
    record = load_bundle(migrated_db, bundle, sign_bundle(manifest, signer), signer.public_key())
    assert (record.version, record.in_force_from) == ("1.0.0", date(2026, 10, 1))
    assert OntologyStore(migrated_db, version="1.0.0").record == record


def test_a_bundle_signed_with_the_release_key_is_not_loaded(migrated_db: str) -> None:
    content = VaultTransitSigner(VAULT, "root", key=KEY)
    release = VaultTransitSigner(VAULT, "root", key="argos-release")
    bundle, manifest = build_bundle(LIBRARY_DIR, "1.0.0", date(2026, 10, 1))
    with pytest.raises(BundleRejectedError, match="signature"):
        load_bundle(migrated_db, bundle, sign_bundle(manifest, release), content.public_key())
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute("SELECT count(*) FROM argos.ontology_bundles").fetchone() == (0,)
