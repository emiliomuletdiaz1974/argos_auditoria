"""Secret stores without external services (ARG-009)."""

from pathlib import Path

import pytest

from argos_common.errors import IntegrityError, SecretNotAccessibleError
from argos_common.secret_stores import EncryptedFileSecretStore, TpmSecretStore


def test_encrypted_file_round_trip(tmp_path: Path) -> None:
    key = EncryptedFileSecretStore.generate_key()
    path = tmp_path / "secrets.bin"
    EncryptedFileSecretStore(path, key).write(
        "services/api/db", {"username": "svc_api", "password": "s3cr3t"}
    )
    assert EncryptedFileSecretStore(path, key).read("services/api/db") == {
        "username": "svc_api",
        "password": "s3cr3t",
    }


def test_file_does_not_contain_the_plaintext_secret(tmp_path: Path) -> None:
    path = tmp_path / "secrets.bin"
    EncryptedFileSecretStore(path, EncryptedFileSecretStore.generate_key()).write(
        "x", {"password": "s3cr3t"}
    )
    assert b"s3cr3t" not in path.read_bytes()


def test_wrong_key_is_an_integrity_error(tmp_path: Path) -> None:
    path = tmp_path / "secrets.bin"
    EncryptedFileSecretStore(path, EncryptedFileSecretStore.generate_key()).write("x", {"a": "b"})
    with pytest.raises(IntegrityError):
        EncryptedFileSecretStore(path, EncryptedFileSecretStore.generate_key()).read("x")


def test_missing_path_is_not_accessible(tmp_path: Path) -> None:
    store = EncryptedFileSecretStore(
        tmp_path / "secrets.bin", EncryptedFileSecretStore.generate_key()
    )
    with pytest.raises(SecretNotAccessibleError):
        store.read("does/not/exist")


def test_tpm_points_to_arg_082() -> None:
    with pytest.raises(NotImplementedError, match="ARG-082"):
        TpmSecretStore().read("x")
