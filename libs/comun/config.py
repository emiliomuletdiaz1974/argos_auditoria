"""Configuración tipada de entorno y parámetros del appliance (Componente ARG-001)."""

from enum import Enum
from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TallaAppliance(str, Enum):
    """Tallas hardware del Servidor Cognitivo Lenovo SR675 V3."""
    S = "S"  # 1 GPU L40S, 32 cores, 128 GB RAM
    M = "M"  # 2 GPU L40S, 64 cores, 256 GB RAM
    L = "L"  # 4 GPU H100/L40S, 128 cores, 512 GB RAM


class ArgosConfig(BaseSettings):
    """Parámetros de configuración del sistema ARGOS."""

    model_config = SettingsConfigDict(
        env_prefix="ARGOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Identidad y versión
    VERSION: str = "0.1.0-alpha"
    ENVIRONMENT: str = Field(default="development", description="development | staging | production")
    TALLA: TallaAppliance = Field(default=TallaAppliance.S, description="Talla del appliance (S, M, L)")

    # Almacén de persistencia (PostgreSQL + AGE + pgvector)
    DATABASE_URL: str = Field(
        default="postgresql://argos:argos_secret@localhost:5432/argos_db",
        description="Cadena de conexión a la base de datos núcleo"
    )

    # Bus de eventos (NATS)
    NATS_URL: str = Field(
        default="nats://localhost:4222",
        description="URL del bus de eventos NATS"
    )

    # Almacén WORM y Evidencias
    WORM_STORAGE_PATH: str = Field(
        default="./data/worm",
        description="Ruta del volumen WORM inmutable de evidencias"
    )

    # Observabilidad
    LOG_LEVEL: str = Field(default="INFO", description="Nivel de registro (DEBUG, INFO, WARNING, ERROR)")
    LOG_FORMAT_JSON: bool = Field(default=True, description="Emisión de logs en formato estructurado JSON")

    # Inferencia IA Local (Fase 06)
    LLM_LOCAL_ENDPOINT: Optional[str] = Field(
        default="http://localhost:8000/v1",
        description="Endpoint del servidor de inferencia local vLLM"
    )


@lru_cache(maxsize=1)
def get_config() -> ArgosConfig:
    """Devuelve la instancia única de configuración en caché."""
    return ArgosConfig()
