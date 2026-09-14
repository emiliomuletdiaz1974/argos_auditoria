"""Jerarquía de excepciones tipadas para la plataforma ARGOS (Componente ARG-001)."""

from typing import Any


class ArgosError(Exception):
    """Excepción raíz de todos los errores controlados de la plataforma ARGOS."""

    def __init__(
        self,
        mensaje: str,
        codigo: str = "ARGOS_GENERIC_ERROR",
        detalles: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.detalles = detalles or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.codigo,
            "mensaje": self.mensaje,
            "detalles": self.detalles,
        }


class ConfiguracionError(ArgosError):
    """Lanzada cuando un parámetro o secreto de configuración es inválido o no existe."""

    def __init__(self, mensaje: str, detalles: dict[str, Any] | None = None) -> None:
        super().__init__(mensaje, codigo="CONFIGURACION_ERROR", detalles=detalles)


class IntegridadError(ArgosError):
    """Lanzada ante la corrupción de un hash, firma o asiento encadenado."""

    def __init__(self, mensaje: str, detalles: dict[str, Any] | None = None) -> None:
        super().__init__(mensaje, codigo="INTEGRIDAD_ERROR", detalles=detalles)


class SoloLecturaError(ArgosError):
    """Lanzada si un conector o actividad intenta realizar una operación de escritura."""

    def __init__(self, mensaje: str, detalles: dict[str, Any] | None = None) -> None:
        super().__init__(mensaje, codigo="VIOLACION_SOLO_LECTURA", detalles=detalles)


class SecretoNoAccesibleError(ArgosError):
    """El secreto no existe o el llamador no tiene permiso: no se distingue a propósito."""

    def __init__(self, mensaje: str, detalles: dict[str, Any] | None = None) -> None:
        super().__init__(mensaje, codigo="SECRETO_NO_ACCESIBLE", detalles=detalles)
