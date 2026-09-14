"""ARG-009 · mínimo privilegio en Vault de desarrollo."""

import os

import hvac
import pytest
from hvac.exceptions import InvalidRequest

from argos_comun.errors import SecretoNoAccesibleError
from argos_comun.secretos import AlmacenVault

pytestmark = pytest.mark.integracion

VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")


@pytest.fixture
def raiz() -> hvac.Client:
    cliente = hvac.Client(url=VAULT, token="root")
    kv = cliente.secrets.kv.v2
    kv.create_or_update_secret(
        path="services/inventory/db", secret={"usuario": "svc_inventory"}, mount_point="argos"
    )
    kv.create_or_update_secret(
        path="services/api/db", secret={"usuario": "svc_api"}, mount_point="argos"
    )
    kv.create_or_update_secret(
        path="connectors/sis-1", secret={"usuario": "lector"}, mount_point="argos"
    )
    return cliente


def _token(raiz: hvac.Client, politica: str) -> str:
    return str(raiz.auth.token.create(policies=[politica], ttl="5m")["auth"]["client_token"])


def test_un_servicio_solo_lee_su_rama(raiz: hvac.Client) -> None:
    almacen = AlmacenVault(VAULT, _token(raiz, "svc-inventory"))
    assert almacen.leer("services/inventory/db") == {"usuario": "svc_inventory"}
    with pytest.raises(SecretoNoAccesibleError):
        almacen.leer("services/api/db")
    with pytest.raises(SecretoNoAccesibleError):
        almacen.leer("connectors/sis-1")


def test_solo_el_sdk_de_conectores_lee_credenciales_de_conectores(raiz: hvac.Client) -> None:
    almacen = AlmacenVault(VAULT, _token(raiz, "svc-connector-sdk"))
    assert almacen.leer("connectors/sis-1") == {"usuario": "lector"}
    with pytest.raises(SecretoNoAccesibleError):
        almacen.leer("services/inventory/db")


def test_pki_emite_certificados_solo_para_dominios_internos(raiz: hvac.Client) -> None:
    cliente = hvac.Client(url=VAULT, token=_token(raiz, "svc-api"))
    emitido = cliente.secrets.pki.generate_certificate(
        name="argos-svc", common_name="api.argos-services", mount_point="pki_int"
    )
    assert emitido["data"]["certificate"].startswith("-----BEGIN CERTIFICATE-----")
    with pytest.raises(InvalidRequest):
        cliente.secrets.pki.generate_certificate(
            name="argos-svc", common_name="banco.example.com", mount_point="pki_int"
        )
