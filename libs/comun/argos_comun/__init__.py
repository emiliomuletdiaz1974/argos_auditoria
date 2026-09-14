"""Librería común y núcleo de la Plataforma ARGOS (Componente ARG-001 / ARG-005)."""

from .config import ArgosConfig, Entorno, NivelLog, TallaAppliance, cargar_config, get_config
from .diario import AsientoDiario, DiarioInmutable, VerificacionDiarioError
from .errors import ArgosError, ConfiguracionError, IntegridadError
from .logs import configurar_logging, get_logger

__all__ = [
    "ArgosConfig",
    "Entorno",
    "NivelLog",
    "TallaAppliance",
    "cargar_config",
    "get_config",
    "AsientoDiario",
    "DiarioInmutable",
    "VerificacionDiarioError",
    "ArgosError",
    "IntegridadError",
    "ConfiguracionError",
    "configurar_logging",
    "get_logger",
]
