"""Diario encadenado v1: hash, canonización y verificación puras (ADR-0002).

La escritura vive en PostgreSQL (`argos.journal_append`, migración 0001); este módulo recalcula
la cadena con una implementación independiente. Una cadena íntegra no demuestra que no se hayan
suprimido asientos del final: eso lo cubre el anclaje de cabeza en cada campaña sellada (ARG-066).
"""

import hashlib
import json
import re
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .errors import IntegridadError

VERSION = b"ARGOS-JOURNAL-v1"
GENESIS: bytes = hashlib.sha256(b"ARGOS-GENESIS").digest()
_AT_CANON = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


class VerificacionDiarioError(IntegridadError):
    """La cadena del diario no es íntegra."""


@dataclass(frozen=True, slots=True)
class Asiento:
    seq: int
    at_canon: str
    actor: str
    action: str
    payload_canon: str
    prev_hash: bytes
    entry_hash: bytes


@dataclass(frozen=True, slots=True)
class Anomalia:
    seq: int
    motivo: str


@dataclass(frozen=True, slots=True)
class ResultadoVerificacion:
    verificados: int
    cabeza_seq: int
    cabeza_hash: bytes
    anomalias: tuple[Anomalia, ...]

    @property
    def integro(self) -> bool:
        return not self.anomalias


def _lp(texto: str) -> bytes:
    datos = texto.encode("utf-8")
    return struct.pack(">I", len(datos)) + datos


def calcular_hash(
    seq: int, at_canon: str, actor: str, action: str, payload_canon: str, prev_hash: bytes
) -> bytes:
    if seq < 1:
        raise ValueError("seq debe ser >= 1")
    if not _AT_CANON.match(at_canon):
        raise ValueError(f"at_canon no tiene el formato canónico: {at_canon!r}")
    if len(prev_hash) != 32:
        raise ValueError("prev_hash debe tener 32 bytes")
    return hashlib.sha256(
        VERSION
        + struct.pack(">Q", seq)
        + _lp(at_canon)
        + _lp(actor)
        + _lp(action)
        + _lp(payload_canon)
        + prev_hash
    ).digest()


def _comprobar_tipos(valor: Any, ruta: str) -> None:
    if valor is None or isinstance(valor, bool | int | str):
        return
    if isinstance(valor, float):
        raise ValueError(f"número de coma flotante no permitido en {ruta}")
    if isinstance(valor, list):
        for i, elemento in enumerate(valor):
            _comprobar_tipos(elemento, f"{ruta}[{i}]")
        return
    if isinstance(valor, dict):
        for clave, elemento in valor.items():
            if not isinstance(clave, str):
                raise ValueError(f"clave no textual en {ruta}")
            _comprobar_tipos(elemento, f"{ruta}.{clave}")
        return
    raise ValueError(f"tipo no admitido en {ruta}: {type(valor).__name__}")


def canonizar(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ValueError("el payload del diario debe ser un objeto JSON")
    _comprobar_tipos(payload, "$")
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def verificar_asientos(
    asientos: Iterable[Asiento], desde_seq: int = 1, prev_hash: bytes = GENESIS
) -> ResultadoVerificacion:
    anomalias: list[Anomalia] = []
    esperado_seq, esperado_prev = desde_seq, prev_hash
    verificados, cabeza_seq, cabeza_hash = 0, desde_seq - 1, prev_hash
    for a in asientos:
        verificados += 1
        if a.seq != esperado_seq:
            anomalias.append(Anomalia(a.seq, f"secuencia rota: se esperaba {esperado_seq}"))
        if a.prev_hash != esperado_prev:
            anomalias.append(Anomalia(a.seq, "prev_hash no enlaza con el asiento anterior"))
        try:
            recalculado = calcular_hash(
                a.seq, a.at_canon, a.actor, a.action, a.payload_canon, a.prev_hash
            )
        except ValueError as exc:
            anomalias.append(Anomalia(a.seq, f"asiento mal formado: {exc}"))
        else:
            if recalculado != a.entry_hash:
                anomalias.append(Anomalia(a.seq, "entry_hash no coincide con el contenido"))
        esperado_seq, esperado_prev = a.seq + 1, a.entry_hash
        cabeza_seq, cabeza_hash = a.seq, a.entry_hash
    return ResultadoVerificacion(verificados, cabeza_seq, cabeza_hash, tuple(anomalias))


def exigir_integridad(resultado: ResultadoVerificacion) -> None:
    if resultado.integro:
        return
    primera = resultado.anomalias[0]
    raise VerificacionDiarioError(
        f"diario no íntegro: primera anomalía en seq={primera.seq} ({primera.motivo})",
        detalles={
            "anomalias": [{"seq": a.seq, "motivo": a.motivo} for a in resultado.anomalias[:20]]
        },
    )
