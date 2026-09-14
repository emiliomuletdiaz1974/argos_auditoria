"""Diario encadenado v1: la suite de integridad se escribe antes que el diario (ADR-0002)."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from argos_comun.diario import (
    GENESIS,
    Asiento,
    VerificacionDiarioError,
    calcular_hash,
    canonizar,
    exigir_integridad,
    verificar_asientos,
)

RUTA = Path(__file__).parents[3] / "tests" / "vectores" / "diario_v1.json"
VECTORES: dict[str, Any] = json.loads(RUTA.read_text(encoding="utf-8"))
T0 = "2026-09-14T10:00:00.000000Z"


def _asientos() -> list[Asiento]:
    return [
        Asiento(
            v["seq"],
            v["at_canon"],
            v["actor"],
            v["action"],
            v["payload_canon"],
            bytes.fromhex(v["prev_hash"]),
            bytes.fromhex(v["entry_hash"]),
        )
        for v in VECTORES["asientos"]
    ]


def test_genesis() -> None:
    assert GENESIS.hex() == VECTORES["genesis"]


@pytest.mark.parametrize("v", VECTORES["asientos"], ids=lambda v: f"seq{v['seq']}")
def test_reproduce_los_vectores(v: dict[str, Any]) -> None:
    obtenido = calcular_hash(
        v["seq"],
        v["at_canon"],
        v["actor"],
        v["action"],
        v["payload_canon"],
        bytes.fromhex(v["prev_hash"]),
    )
    assert obtenido.hex() == v["entry_hash"]


def test_canonizar_reproduce_los_vectores() -> None:
    a = VECTORES["asientos"]
    assert canonizar({"version": 1, "checksum": "abc"}) == a[0]["payload_canon"]
    segundo = canonizar({"nota": "Aprobación con ñ y €", "campaign_id": "c-1"})
    assert segundo == a[1]["payload_canon"]


def test_canonizar_rechaza_flotantes_indicando_la_ruta() -> None:
    with pytest.raises(ValueError, match=r"\$\.a\[1\]"):
        canonizar({"a": [1, 2.5]})


def test_canonizar_rechaza_tipos_no_json() -> None:
    with pytest.raises(ValueError, match="bytes"):
        canonizar({"a": b"x"})


def test_prefijo_de_longitud_evita_ambiguedad() -> None:
    assert calcular_hash(1, T0, "ab", "c", "{}", GENESIS) != calcular_hash(
        1, T0, "a", "bc", "{}", GENESIS
    )


def test_rechaza_entradas_mal_formadas() -> None:
    with pytest.raises(ValueError):
        calcular_hash(0, T0, "a", "b", "{}", GENESIS)
    with pytest.raises(ValueError):
        calcular_hash(1, "2026-09-14 10:00:00", "a", "b", "{}", GENESIS)
    with pytest.raises(ValueError):
        calcular_hash(1, T0, "a", "b", "{}", b"corto")


def test_cadena_integra() -> None:
    r = verificar_asientos(_asientos())
    assert r.integro
    assert (r.verificados, r.cabeza_seq) == (3, 3)
    assert r.cabeza_hash.hex() == VECTORES["asientos"][2]["entry_hash"]


def test_contenido_alterado_senala_la_posicion() -> None:
    a = _asientos()
    a[1] = replace(a[1], payload_canon='{"campaign_id":"c-2","nota":"x"}')
    r = verificar_asientos(a)
    assert not r.integro
    assert [an.seq for an in r.anomalias] == [2]


def test_supresion_de_un_asiento() -> None:
    a = _asientos()
    r = verificar_asientos([a[0], a[2]])
    assert not r.integro
    assert {an.seq for an in r.anomalias} == {3}


def test_asiento_insertado_rompe_el_enlace() -> None:
    a = _asientos()
    intruso = replace(a[1], actor="user:intruso")
    r = verificar_asientos([a[0], a[1], intruso, a[2]])
    assert not r.integro


def test_verificacion_por_rango() -> None:
    a = _asientos()
    r = verificar_asientos(a[1:], desde_seq=2, prev_hash=a[0].entry_hash)
    assert r.integro and r.verificados == 2


def test_formato_de_fecha_invalido_es_anomalia_no_excepcion() -> None:
    a = _asientos()
    a[0] = replace(a[0], at_canon="2026-09-14 10:00:00")
    r = verificar_asientos(a)
    assert r.anomalias[0].seq == 1


def test_cadena_vacia_es_integra() -> None:
    r = verificar_asientos([])
    assert r.integro and r.verificados == 0 and r.cabeza_hash == GENESIS


def test_exigir_integridad_lanza_con_detalles() -> None:
    a = _asientos()
    a[2] = replace(a[2], actor="system:otro")
    with pytest.raises(VerificacionDiarioError) as exc:
        exigir_integridad(verificar_asientos(a))
    assert exc.value.detalles["anomalias"][0]["seq"] == 3
