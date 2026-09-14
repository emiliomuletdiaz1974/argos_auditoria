"""Secret access through a single interface (ARG-009). Values are never logged."""

import json
from pathlib import Path
from typing import Protocol

import hvac
from cryptography.fernet import Fernet, InvalidToken
from hvac.exceptions import Forbidden, InvalidPath

from .errors import IntegrityError, SecretNotAccessibleError


class SecretStore(Protocol):
    def read(self, path: str) -> dict[str, str]: ...


class VaultSecretStore:
    """Vault kv-v2; each token only sees the paths its policy allows."""

    def __init__(self, url: str, token: str, mount: str = "argos") -> None:
        self._client = hvac.Client(url=url, token=token)
        self._mount = mount

    def read(self, path: str) -> dict[str, str]:
        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path, mount_point=self._mount, raise_on_deleted_version=True
            )
        except (Forbidden, InvalidPath):
            raise SecretNotAccessibleError(
                "secret not accessible", details={"path": path}
            ) from None
        data = response["data"]["data"]
        return {str(k): str(v) for k, v in data.items()}


class EncryptedFileSecretStore:
    """Development without Vault only: a Fernet file holding {path: {key: value}}."""

    def __init__(self, path: Path, key: bytes) -> None:
        self._path = path
        self._fernet = Fernet(key)

    @staticmethod
    def generate_key() -> bytes:
        return Fernet.generate_key()

    def _load(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        try:
            decrypted = self._fernet.decrypt(self._path.read_bytes())
        except InvalidToken:
            raise IntegrityError("secrets file is corrupted or the key is wrong") from None
        content: dict[str, dict[str, str]] = json.loads(decrypted)
        return content

    def read(self, path: str) -> dict[str, str]:
        content = self._load()
        if path not in content:
            raise SecretNotAccessibleError("secret not accessible", details={"path": path})
        return dict(content[path])

    def write(self, path: str, data: dict[str, str]) -> None:
        content = self._load()
        content[path] = dict(data)
        self._path.write_bytes(self._fernet.encrypt(json.dumps(content).encode("utf-8")))


class TpmSecretStore:
    """Secrets sealed by the appliance TPM: implemented together with measured boot."""

    def read(self, path: str) -> dict[str, str]:
        raise NotImplementedError("TPM secret sealing is implemented in ARG-082 (Phase 09)")
