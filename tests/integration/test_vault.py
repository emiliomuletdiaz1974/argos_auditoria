"""ARG-009 · least privilege in the development Vault."""

import os

import hvac
import pytest
from hvac.exceptions import InvalidRequest

from argos_common.errors import SecretNotAccessibleError
from argos_common.secret_stores import VaultSecretStore

pytestmark = pytest.mark.integration

VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")


@pytest.fixture
def root() -> hvac.Client:
    client = hvac.Client(url=VAULT, token="root")
    kv = client.secrets.kv.v2
    kv.create_or_update_secret(
        path="services/inventory/db", secret={"username": "svc_inventory"}, mount_point="argos"
    )
    kv.create_or_update_secret(
        path="services/api/db", secret={"username": "svc_api"}, mount_point="argos"
    )
    kv.create_or_update_secret(
        path="connectors/sis-1", secret={"username": "reader"}, mount_point="argos"
    )
    return client


def _token(root: hvac.Client, policy: str) -> str:
    return str(root.auth.token.create(policies=[policy], ttl="5m")["auth"]["client_token"])


def test_a_service_only_reads_its_own_branch(root: hvac.Client) -> None:
    store = VaultSecretStore(VAULT, _token(root, "svc-inventory"))
    assert store.read("services/inventory/db") == {"username": "svc_inventory"}
    with pytest.raises(SecretNotAccessibleError):
        store.read("services/api/db")
    with pytest.raises(SecretNotAccessibleError):
        store.read("connectors/sis-1")


def test_only_the_connector_sdk_reads_connector_credentials(root: hvac.Client) -> None:
    store = VaultSecretStore(VAULT, _token(root, "svc-connector-sdk"))
    assert store.read("connectors/sis-1") == {"username": "reader"}
    with pytest.raises(SecretNotAccessibleError):
        store.read("services/inventory/db")


def test_pki_issues_certificates_only_for_internal_domains(root: hvac.Client) -> None:
    client = hvac.Client(url=VAULT, token=_token(root, "svc-api"))
    issued = client.secrets.pki.generate_certificate(
        name="argos-svc", common_name="api.argos-services", mount_point="pki_int"
    )
    assert issued["data"]["certificate"].startswith("-----BEGIN CERTIFICATE-----")
    with pytest.raises(InvalidRequest):
        client.secrets.pki.generate_certificate(
            name="argos-svc", common_name="bank.example.com", mount_point="pki_int"
        )
