"""Typed appliance configuration; a misconfigured service refuses to start (ARG-001)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Self
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import Field, SecretStr, ValidationError, model_validator
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
    # Hidden from repr: with DATABASE_PASSWORD_FILE the connection string carries the password.
    DATABASE_URL: str = Field(min_length=1, repr=False)
    # The service's database password, mounted as a secret file (F09-04); never in the URL itself.
    DATABASE_PASSWORD_FILE: str | None = None
    # F09-05 (ARG-085): the role of Vault's `db/` engine that issues this service's ephemeral
    # user. Set, the credential lives in DATABASE_SERVICE_FILE and DATABASE_URL names no user
    # (`...?service=argos`). The AppRole to log in with is two files in VAULT_APPROLE_DIR.
    DATABASE_VAULT_ROLE: str | None = None
    DATABASE_SERVICE_FILE: str = "/tmp/argos-db/pg_service.conf"  # noqa: S108 - tmpfs of the container
    VAULT_APPROLE_DIR: str | None = None
    # F09-06 (ARG-083): the folder with this service's certificate, key and internal CA
    # (tls.crt, tls.key, ca.crt). Set, the service speaks mutual TLS to the other ARGOS services.
    TLS_DIR: str | None = None
    # F09-10 (ARG-086): the folder of the updater (inbox/, queue/, version) and the pinned release
    # key the API verifies a bundle with before it queues it. Unset: the API takes no updates.
    UPDATE_DIR: str | None = None
    RELEASE_PUBLIC_KEY_FILE: str | None = None
    # F09-11 (ARG-088): the folder shared with the diagnostics collector (queue/, previews/) and
    # the age public key of support. Unset: the API offers no diagnostic packages.
    SUPPORT_DIR: str | None = None
    SUPPORT_RECIPIENT_FILE: str | None = None
    NATS_URL: str = "nats://127.0.0.1:4222"
    # Each service connects with its own NATS user: the server decides what it may publish.
    NATS_USER: str | None = None
    NATS_PASSWORD: SecretStr | None = None
    TEMPORAL_ADDRESS: str = "127.0.0.1:7233"
    OIDC_ISSUER: str = "http://127.0.0.1:8180/realms/argos"
    OIDC_AUDIENCE: str = "argos-api"
    WORM_STORAGE_PATH: str = "./data/worm"
    LOG_LEVEL: LogLevel = LogLevel.INFO
    LOG_FORMAT_JSON: bool = True
    LLM_LOCAL_ENDPOINT: str | None = "http://127.0.0.1:8000/v1"
    LLM_MODEL: str = "argos-llm"  # the served model name, never a model in code (ADR-0009)
    EMBEDDING_MODEL: str = "argos-embed"  # the served embedding model name (ADR-0009)
    # Private destinations a webhook may reach (the client's ITSM), comma-separated host names
    # or networks. Empty: only public https destinations (security review F09-02, SEC-031).
    WEBHOOK_ALLOWED_TARGETS: str = ""
    OPA_URL: str = "http://127.0.0.1:8181"  # operational rules of the challenge engine (ARG-036)
    OPA_TOKEN: SecretStr | None = None  # bearer token OPA accepts for evaluating argos.* packages
    VAULT_ADDR: str = "http://127.0.0.1:8200"
    VAULT_TOKEN: SecretStr | None = None  # services that open connectors: svc-connector-sdk policy

    @model_validator(mode="after")
    def _database_password(self) -> Self:
        if self.DATABASE_PASSWORD_FILE is None:
            return self
        try:
            password = Path(self.DATABASE_PASSWORD_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            raise ValueError("DATABASE_PASSWORD_FILE cannot be read") from None
        if not password:
            raise ValueError("DATABASE_PASSWORD_FILE is empty")
        parts = urlsplit(self.DATABASE_URL)
        user, _, host = parts.netloc.rpartition("@")
        if not user:
            raise ValueError("DATABASE_URL must name its user when the password is in a file")
        if ":" in user:
            raise ValueError(
                "DATABASE_URL must not carry a password when DATABASE_PASSWORD_FILE is set"
            )
        netloc = f"{user}:{quote(password, safe='')}@{host}"
        self.DATABASE_URL = urlunsplit(parts._replace(netloc=netloc))
        return self

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
        if not self.OIDC_ISSUER.startswith("https://"):
            raise ValueError("OIDC_ISSUER must use https in production")
        # Tokens, credentials and the policies that decide verdicts travel on these links.
        encrypted = {
            "VAULT_ADDR": self.VAULT_ADDR.startswith("https://"),
            "NATS_URL": self.NATS_URL.startswith("tls://"),
            "OPA_URL": self.OPA_URL.startswith("https://"),
            "LLM_LOCAL_ENDPOINT": self.LLM_LOCAL_ENDPOINT is None
            or self.LLM_LOCAL_ENDPOINT.startswith("https://"),
        }
        for field, ok in encrypted.items():
            if not ok:
                raise ValueError(f"{field} must use an encrypted transport in production")
        # NATS carries the discovery events the inventory trusts and OPA decides verdicts:
        # neither answers an anonymous client in production.
        for field in ("NATS_USER", "NATS_PASSWORD", "OPA_TOKEN"):
            if not getattr(self, field):
                raise ValueError(f"{field} is required in production")
        if self.VAULT_TOKEN is not None and self.VAULT_TOKEN.get_secret_value() == "root":
            raise ValueError("VAULT_TOKEN must be a scoped service token in production")
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
