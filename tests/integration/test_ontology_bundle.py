"""ARG-040 · bundles signed with the Vault content key load only when verified."""

import os
import shutil
from datetime import date
from pathlib import Path

import hvac
import psycopg
import pytest

from argos_common.errors import IntegrityError
from argos_common.release import VaultTransitSigner, key_fingerprint
from argos_ontology.bundle import (
    CONTENT_KEY,
    BundleRejectedError,
    build_bundle,
    load_bundle,
    sign_bundle,
    verify_on_disk,
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
    record = load_bundle(
        migrated_db,
        bundle,
        sign_bundle(manifest, signer),
        signer.public_key(),
        fingerprint=key_fingerprint(signer.public_key()),
    )
    assert (record.version, record.in_force_from) == ("1.0.0", date(2026, 10, 1))
    assert OntologyStore(migrated_db, version="1.0.0").record == record


def test_a_bundle_signed_with_the_release_key_is_not_loaded(migrated_db: str) -> None:
    content = VaultTransitSigner(VAULT, "root", key=KEY)
    release = VaultTransitSigner(VAULT, "root", key="argos-release")
    bundle, manifest = build_bundle(LIBRARY_DIR, "1.0.0", date(2026, 10, 1))
    with pytest.raises(BundleRejectedError, match="signature"):
        load_bundle(
            migrated_db,
            bundle,
            sign_bundle(manifest, release),
            content.public_key(),
            fingerprint=key_fingerprint(content.public_key()),
        )
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute("SELECT count(*) FROM argos.ontology_bundles").fetchone() == (0,)


# ---------- pinned key, no rollback, content in force (security review F09-02) ----------


def _signed(version: str, library: Path = LIBRARY_DIR) -> tuple[bytes, bytes, bytes, str]:
    signer = VaultTransitSigner(VAULT, "root", key=KEY)
    bundle, manifest = build_bundle(library, version, date(2026, 10, 1))
    public_key = signer.public_key()
    return bundle, sign_bundle(manifest, signer), public_key, key_fingerprint(public_key)


def test_a_key_that_is_not_the_pinned_one_is_refused(migrated_db: str) -> None:
    """SEC-020: the key beside a bundle proves nothing without its pinned fingerprint."""
    bundle, signature, public_key, _ = _signed("1.0.0")
    with pytest.raises(IntegrityError, match="trusted"):
        load_bundle(migrated_db, bundle, signature, public_key, fingerprint="00" * 32)


def test_an_older_version_does_not_replace_a_newer_one(migrated_db: str) -> None:
    """SEC-020: loading 1.1.0 after 1.1.1 would bring back what 1.1.1 corrected."""
    bundle, signature, public_key, fingerprint = _signed("1.1.1")
    load_bundle(migrated_db, bundle, signature, public_key, fingerprint=fingerprint)
    older, older_signature, _, _ = _signed("1.1.0")
    with pytest.raises(BundleRejectedError, match="older"):
        load_bundle(migrated_db, older, older_signature, public_key, fingerprint=fingerprint)
    record = load_bundle(
        migrated_db,
        older,
        older_signature,
        public_key,
        fingerprint=fingerprint,
        allow_rollback=True,
    )
    assert record.version == "1.1.0"


def test_the_content_on_disk_is_checked_against_the_signed_manifest(
    migrated_db: str, tmp_path: Path
) -> None:
    """SEC-011: what runs is what was signed; a changed policy on disk stops the campaign."""
    library = tmp_path / "library"
    shutil.copytree(LIBRARY_DIR, library)
    bundle, signature, public_key, fingerprint = _signed("1.0.0", library)
    load_bundle(migrated_db, bundle, signature, public_key, fingerprint=fingerprint)
    verify_on_disk(migrated_db, "1.0.0", library)
    rego = next((library / "policies").glob("*.rego"))
    rego.write_text(rego.read_text(encoding="utf-8") + "\n# softened\n", encoding="utf-8")
    with pytest.raises(IntegrityError, match="policies/"):
        verify_on_disk(migrated_db, "1.0.0", library)
