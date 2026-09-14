"""Logging estructurado JSON con campos obligatorios (ARG-001; lo consume Loki en ARG-093)."""

import json
import logging
import re
import sys
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any, TextIO

CAMPOS_OPCIONALES = ("journal_seq", "trace_id", "campana_id")
_MARCA = "_argos_manejador"
_COMPONENTE = re.compile(r"^ARG-\d{3}$")


class FormateadorJSON(logging.Formatter):
    def __init__(self, servicio: str) -> None:
        super().__init__()
        self.servicio = servicio

    def format(self, record: logging.LogRecord) -> str:
        entrada: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="microseconds"
            ),
            "level": record.levelname,
            "servicio": self.servicio,
            "componente": getattr(record, "componente", "sin-componente"),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for campo in CAMPOS_OPCIONALES:
            valor = getattr(record, campo, None)
            if valor is not None:
                entrada[campo] = valor
        if record.exc_info:
            entrada["exception"] = self.formatException(record.exc_info)
        return json.dumps(entrada, ensure_ascii=False, default=str)


class _AdaptadorArgos(logging.LoggerAdapter[logging.Logger]):
    """Combina el componente fijo con el `extra` de cada llamada (3.12 lo descartaría)."""

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        kwargs["extra"] = {**(self.extra or {}), **kwargs.get("extra", {})}
        return msg, kwargs


def configurar_logging(servicio: str, nivel: str = "INFO", flujo: TextIO | None = None) -> None:
    raiz = logging.getLogger()
    for manejador in [h for h in raiz.handlers if getattr(h, _MARCA, False)]:
        raiz.removeHandler(manejador)
    nuevo = logging.StreamHandler(flujo or sys.stdout)
    nuevo.setFormatter(FormateadorJSON(servicio))
    setattr(nuevo, _MARCA, True)
    raiz.addHandler(nuevo)
    raiz.setLevel(str(nivel).upper())


def get_logger(nombre: str, componente: str) -> logging.LoggerAdapter[logging.Logger]:
    if not _COMPONENTE.match(componente):
        raise ValueError(f"componente debe tener formato ARG-NNN, recibido {componente!r}")
    return _AdaptadorArgos(logging.getLogger(nombre), {"componente": componente})
