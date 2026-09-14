"""Configuración tipada del appliance; un servicio mal configurado no arranca (ARG-001)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import PurePosixPath, PureWindowsPath
from typing import Self

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import ConfiguracionError


class Entorno(StrEnum):
    DESARROLLO = "development"
    PREPRODUCCION = "staging"
    PRODUCCION = "production"


class NivelLog(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class TallaAppliance(StrEnum):
    """Tallas del Servidor Cognitivo (Especificación Técnica §5)."""

    S = "S"
    M = "M"
    L = "L"


_HOSTS_LOCALES = ("127.0.0.1", "localhost", "@localhost", "::1")


class ArgosConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARGOS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    VERSION: str = "0.1.0-alpha"
    ENVIRONMENT: Entorno = Entorno.DESARROLLO
    TALLA: TallaAppliance = TallaAppliance.S
    DATABASE_URL: str = Field(min_length=1)
    NATS_URL: str = "nats://127.0.0.1:4222"
    TEMPORAL_ADDRESS: str = "127.0.0.1:7233"
    WORM_STORAGE_PATH: str = "./data/worm"
    LOG_LEVEL: NivelLog = NivelLog.INFO
    LOG_FORMAT_JSON: bool = True
    LLM_LOCAL_ENDPOINT: str | None = "http://127.0.0.1:8000/v1"

    @model_validator(mode="after")
    def _reglas_de_produccion(self) -> Self:
        if self.ENVIRONMENT is not Entorno.PRODUCCION:
            return self
        if any(h in self.DATABASE_URL for h in _HOSTS_LOCALES):
            raise ValueError("DATABASE_URL de producción no puede apuntar a una base local")
        ruta = self.WORM_STORAGE_PATH
        if not (PurePosixPath(ruta).is_absolute() or PureWindowsPath(ruta).is_absolute()):
            raise ValueError("WORM_STORAGE_PATH debe ser absoluta en producción")
        if not self.LOG_FORMAT_JSON:
            raise ValueError("LOG_FORMAT_JSON debe ser true en producción")
        return self


def cargar_config() -> ArgosConfig:
    """Construye y valida la configuración; los errores no incluyen los valores recibidos."""
    try:
        return ArgosConfig()  # DATABASE_URL llega del entorno o del .env
    except ValidationError as exc:
        errores = [
            {"campo": ".".join(str(p) for p in e["loc"]) or "general", "mensaje": e["msg"]}
            for e in exc.errors(include_input=False, include_url=False)
        ]
        raise ConfiguracionError("configuración inválida", detalles={"errores": errores}) from None


@lru_cache(maxsize=1)
def get_config() -> ArgosConfig:
    return cargar_config()
