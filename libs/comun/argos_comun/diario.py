"""Diario Inmutable encadenado por SHA-256 (Componente ARG-005).

Garantiza la trazabilidad forense no repudiable de cada operación y evidencia
en la plataforma ARGOS. Ningún asiento puede modificarse o eliminarse sin
invalidar la cadena matemática completa.
"""

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from .errors import IntegridadError


class VerificacionDiarioError(IntegridadError):
    """Lanzada cuando un asiento o la cadena del diario inmutable está corrupta o rota."""

    pass


GENESIS_HASH = "0" * 64


class AsientoDiario(BaseModel):
    """Representa un asiento inmutable en el diario de auditoría."""

    seq: int = Field(ge=1, description="Número de secuencia estrictamente incremental")
    timestamp: str = Field(description="Timestamp UTC en formato ISO 8601")
    componente: str = Field(
        pattern=r"^ARG-\d{3}$", description="Identificador del componente emisor"
    )
    operacion: str = Field(description="Nombre de la operación registrada")
    actor: str = Field(description="Entidad o proceso que originó el evento")
    payload_hash: str = Field(
        min_length=64, max_length=64, description="Hash SHA-256 del payload o evidencia"
    )
    detalles: dict[str, Any] = Field(
        default_factory=dict, description="Metadatos contextuales canónicos"
    )
    hash_previo: str = Field(min_length=64, max_length=64, description="Hash del asiento anterior")
    hash_actual: str = Field(
        min_length=64, max_length=64, description="Hash SHA-256 canónico del asiento"
    )

    @classmethod
    def calcular_hash(
        cls,
        seq: int,
        timestamp: str,
        componente: str,
        operacion: str,
        actor: str,
        payload_hash: str,
        detalles: dict[str, Any],
        hash_previo: str,
    ) -> str:
        """Calcula el hash SHA-256 de forma estrictamente canónica y reproducible."""
        datos_canonicos = {
            "seq": seq,
            "timestamp": timestamp,
            "componente": componente,
            "operacion": operacion,
            "actor": actor,
            "payload_hash": payload_hash,
            "detalles": detalles,
            "hash_previo": hash_previo,
        }
        bytes_canonicos = json.dumps(
            datos_canonicos, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(bytes_canonicos).hexdigest()

    def es_valido(self) -> bool:
        """Comprueba que el hash actual coincida exactamente con los datos contenidos."""
        esperado = self.calcular_hash(
            seq=self.seq,
            timestamp=self.timestamp,
            componente=self.componente,
            operacion=self.operacion,
            actor=self.actor,
            payload_hash=self.payload_hash,
            detalles=self.detalles,
            hash_previo=self.hash_previo,
        )
        return self.hash_actual == esperado


class DiarioInmutable:
    """Gestor del diario de auditoría con verificación continua de cadena."""

    def __init__(self, asientos_iniciales: list[AsientoDiario] | None = None) -> None:
        self._cadena: list[AsientoDiario] = []
        if asientos_iniciales:
            self.verificar_y_cargar(asientos_iniciales)

    @property
    def longitud(self) -> int:
        return len(self._cadena)

    @property
    def ultimo_asiento(self) -> AsientoDiario | None:
        return self._cadena[-1] if self._cadena else None

    def registrar(
        self,
        componente: str,
        operacion: str,
        actor: str,
        payload_bytes: bytes,
        detalles: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> AsientoDiario:
        """Crea y concatena un nuevo asiento al final del diario inmutable."""
        if detalles is None:
            detalles = {}

        seq = len(self._cadena) + 1
        ts = timestamp or datetime.now(UTC).isoformat()
        hash_previo = self._cadena[-1].hash_actual if self._cadena else GENESIS_HASH
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()

        hash_actual = AsientoDiario.calcular_hash(
            seq=seq,
            timestamp=ts,
            componente=componente,
            operacion=operacion,
            actor=actor,
            payload_hash=payload_hash,
            detalles=detalles,
            hash_previo=hash_previo,
        )

        asiento = AsientoDiario(
            seq=seq,
            timestamp=ts,
            componente=componente,
            operacion=operacion,
            actor=actor,
            payload_hash=payload_hash,
            detalles=detalles,
            hash_previo=hash_previo,
            hash_actual=hash_actual,
        )

        self._cadena.append(asiento)
        return asiento

    def verificar_cadena(self) -> bool:
        """Verifica la integridad de cada eslabón de la cadena completa."""
        return self.verificar_asientos(self._cadena)

    @classmethod
    def verificar_asientos(cls, asientos: Sequence[AsientoDiario]) -> bool:
        """Verifica que una secuencia de asientos sea matemáticamente íntegra."""
        hash_esperado_previo = GENESIS_HASH
        for i, asiento in enumerate(asientos, start=1):
            if asiento.seq != i:
                raise VerificacionDiarioError(
                    f"Secuencia rota en posición {i}: encontrado seq={asiento.seq}",
                    detalles={"posicion": i, "seq_encontrado": asiento.seq},
                )

            if asiento.hash_previo != hash_esperado_previo:
                raise VerificacionDiarioError(
                    f"Hash previo inválido en asiento seq={asiento.seq}. Cadena rota.",
                    detalles={
                        "seq": asiento.seq,
                        "esperado": hash_esperado_previo,
                        "recibido": asiento.hash_previo,
                    },
                )

            if not asiento.es_valido():
                raise VerificacionDiarioError(
                    f"Corrupción de datos en asiento seq={asiento.seq}. "
                    "Hash actual no coincide con el contenido.",
                    detalles={"seq": asiento.seq, "hash_actual": asiento.hash_actual},
                )

            hash_esperado_previo = asiento.hash_actual

        return True

    def verificar_y_cargar(self, asientos: Sequence[AsientoDiario]) -> None:
        """Valida una lista de asientos antes de adoptarla como estado interno."""
        self.verificar_asientos(asientos)
        self._cadena = list(asientos)
