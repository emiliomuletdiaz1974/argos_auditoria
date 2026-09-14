"""Typed appliance configuration; a misconfigured service refuses to start (ARG-001)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import PurePosixPath, PureWindowsPath
from typing import Self

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import ConfigurationError


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ApplianceSize(StrEnum):
    """Cognitive Server sizes (Technical Specification §5)."""

    S = "S"
    M = "M"
    L = "L"


_LOCAL_HOSTS = ("127.0.0.1", "localhost", "@localhost", "::1")


class ArgosConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARGOS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    VERSION: str = "0.1.0-alpha"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    APPLIANCE_SIZE: ApplianceSize = ApplianceSize.S
    DATABASE_URL: str = Field(min_length=1)
    NATS_URL: str = "nats://127.0.0.1:4222"
    TEMPORAL_ADDRESS: str = "127.0.0.1:7233"
    WORM_STORAGE_PATH: str = "./data/worm"
    LOG_LEVEL: LogLevel = LogLevel.INFO
    LOG_FORMAT_JSON: bool = True
    LLM_LOCAL_ENDPOINT: str | None = "http://127.0.0.1:8000/v1"

    @model_validator(mode="after")
    def _production_rules(self) -> Self:
        if self.ENVIRONMENT is not Environment.PRODUCTION:
            return self
        if any(h in self.DATABASE_URL for h in _LOCAL_HOSTS):
            raise ValueError("production DATABASE_URL must not point to a local database")
        path = self.WORM_STORAGE_PATH
        if not (PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()):
            raise ValueError("WORM_STORAGE_PATH must be absolute in production")
        if not self.LOG_FORMAT_JSON:
            raise ValueError("LOG_FORMAT_JSON must be true in production")
        return self


def load_config() -> ArgosConfig:
    """Build and validate the configuration; errors never include the received values."""
    try:
        return ArgosConfig()  # DATABASE_URL comes from the environment or the .env file
    except ValidationError as exc:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"]) or "general", "message": e["msg"]}
            for e in exc.errors(include_input=False, include_url=False)
        ]
        raise ConfigurationError("invalid configuration", details={"errors": errors}) from None


@lru_cache(maxsize=1)
def get_config() -> ArgosConfig:
    return load_config()
