"""Librería común y núcleo de la Plataforma ARGOS (Componente ARG-001 / ARG-005)."""

from .config import ArgosConfig, Entorno, NivelLog, TallaAppliance, cargar_config, get_config
from .diario import (
    GENESIS,
    Anomalia,
    Asiento,
    ResultadoVerificacion,
    VerificacionDiarioError,
    calcular_hash,
    canonizar,
    exigir_integridad,
    verificar_asientos,
)
from .diario_pg import DiarioPostgres
from .errors import ArgosError, ConfiguracionError, IntegridadError
from .logs import configurar_logging, get_logger
from .salud import montar_salud

__all__ = [
    "ArgosConfig",
    "Entorno",
    "NivelLog",
    "TallaAppliance",
    "cargar_config",
    "get_config",
    "GENESIS",
    "Anomalia",
    "Asiento",
    "ResultadoVerificacion",
    "VerificacionDiarioError",
    "calcular_hash",
    "canonizar",
    "exigir_integridad",
    "verificar_asientos",
    "DiarioPostgres",
    "ArgosError",
    "IntegridadError",
    "ConfiguracionError",
    "configurar_logging",
    "get_logger",
    "montar_salud",
]
