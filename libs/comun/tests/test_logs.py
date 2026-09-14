"""Logging estructurado con campos obligatorios (ARG-001)."""

import io
import json
from typing import Any

import pytest

from argos_comun.logs import configurar_logging, get_logger


def _lineas(flujo: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(linea) for linea in flujo.getvalue().splitlines()]


def test_campos_obligatorios() -> None:
    flujo = io.StringIO()
    configurar_logging("svc-prueba", "INFO", flujo)
    get_logger("prueba", "ARG-005").info("hola ñ")
    [entrada] = _lineas(flujo)
    assert {"timestamp", "level", "servicio", "componente", "logger", "message"} <= entrada.keys()
    assert entrada["servicio"] == "svc-prueba"
    assert entrada["componente"] == "ARG-005"
    assert entrada["message"] == "hola ñ"
    assert entrada["timestamp"].endswith("+00:00")


def test_campos_opcionales_por_llamada_sin_perder_componente() -> None:
    flujo = io.StringIO()
    configurar_logging("svc", "INFO", flujo)
    get_logger("prueba", "ARG-012").info("asiento", extra={"journal_seq": 42, "trace_id": "t-1"})
    [entrada] = _lineas(flujo)
    assert entrada["journal_seq"] == 42
    assert entrada["trace_id"] == "t-1"
    assert entrada["componente"] == "ARG-012"
    assert "campana_id" not in entrada


def test_respeta_el_nivel() -> None:
    flujo = io.StringIO()
    configurar_logging("svc", "WARNING", flujo)
    log = get_logger("prueba", "ARG-001")
    log.info("no")
    log.warning("sí")
    assert [e["message"] for e in _lineas(flujo)] == ["sí"]


def test_reconfigurar_no_duplica_salidas() -> None:
    flujo = io.StringIO()
    configurar_logging("svc", "INFO", io.StringIO())
    configurar_logging("svc", "INFO", flujo)
    get_logger("prueba", "ARG-001").info("una vez")
    assert len(_lineas(flujo)) == 1


def test_serializa_excepciones() -> None:
    flujo = io.StringIO()
    configurar_logging("svc", "INFO", flujo)
    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        get_logger("prueba", "ARG-001").exception("fallo")
    assert "ZeroDivisionError" in _lineas(flujo)[0]["exception"]


def test_componente_con_formato_invalido() -> None:
    with pytest.raises(ValueError, match="ARG-NNN"):
        get_logger("prueba", "ARGOS")
