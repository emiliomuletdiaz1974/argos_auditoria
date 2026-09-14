"""Almacenes de secretos sin servicios externos (ARG-009)."""

from pathlib import Path

import pytest

from argos_comun.errors import IntegridadError, SecretoNoAccesibleError
from argos_comun.secretos import AlmacenFicheroCifrado, AlmacenTPM


def test_fichero_cifrado_ida_y_vuelta(tmp_path: Path) -> None:
    clave = AlmacenFicheroCifrado.crear_clave()
    ruta = tmp_path / "secretos.bin"
    AlmacenFicheroCifrado(ruta, clave).escribir(
        "services/api/db", {"usuario": "svc_api", "clave": "s3cr3t"}
    )
    assert AlmacenFicheroCifrado(ruta, clave).leer("services/api/db") == {
        "usuario": "svc_api",
        "clave": "s3cr3t",
    }


def test_el_fichero_no_contiene_el_secreto_en_claro(tmp_path: Path) -> None:
    ruta = tmp_path / "secretos.bin"
    AlmacenFicheroCifrado(ruta, AlmacenFicheroCifrado.crear_clave()).escribir(
        "x", {"clave": "s3cr3t"}
    )
    assert b"s3cr3t" not in ruta.read_bytes()


def test_clave_incorrecta_es_error_de_integridad(tmp_path: Path) -> None:
    ruta = tmp_path / "secretos.bin"
    AlmacenFicheroCifrado(ruta, AlmacenFicheroCifrado.crear_clave()).escribir("x", {"a": "b"})
    with pytest.raises(IntegridadError):
        AlmacenFicheroCifrado(ruta, AlmacenFicheroCifrado.crear_clave()).leer("x")


def test_ruta_inexistente_no_es_accesible(tmp_path: Path) -> None:
    almacen = AlmacenFicheroCifrado(tmp_path / "secretos.bin", AlmacenFicheroCifrado.crear_clave())
    with pytest.raises(SecretoNoAccesibleError):
        almacen.leer("no/existe")


def test_tpm_remite_a_arg_082() -> None:
    with pytest.raises(NotImplementedError, match="ARG-082"):
        AlmacenTPM().leer("x")
