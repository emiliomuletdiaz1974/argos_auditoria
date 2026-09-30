"""Typed appliance configuration; a misconfigured service refuses to start (ARG-001)."""

import ipaddress
from enum import StrEnum
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Self
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

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


def _origin(raw: str) -> str:
    return raw.strip().lower().rstrip("/")


def _is_local(host: str | None) -> bool:
    """Whether a host is this machine: by its name or its address, not by a substring of the URL
    (`pg.localhost-cluster.example` is not local; quality review QA-010)."""
    if not host:
        return True
    name = host.lower().rstrip(".")
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


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
    # F09-13 (ARG-090): the airlock (in/ read-only, out/ and work/) and the content key pinned
    # to verify normative bundles that come in through it. Unset: no airlock.
    AIRGAP_DIR: str | None = None
    CONTENT_PUBLIC_KEY_FILE: str | None = None
    # F10-07 (ARG-092/099): the operation screen reads its lights from Prometheus and shows the
    # runbooks of RUNBOOKS_DIR; Alertmanager delivers its alerts with the token of the file.
    # Unset: no lights, no runbooks, and the receiver of alerts stays closed.
    PROMETHEUS_URL: str | None = None
    RUNBOOKS_DIR: str | None = None
    ALERTMANAGER_TOKEN_FILE: str | None = None
    # F10-08 (ARG-098): the size of the appliance (S, M or L) and the file of the sizes. Unset:
    # nothing is limited and the capacity report says the size is not configured.
    SIZE: str | None = None
    SIZES_FILE: str | None = None
    # F10-10 (ARG-096): where the installer left its state and its signed report; the airlock
    # exports the report from there. Unset: there is no report to export.
    INSTALL_DIR: str | None = None
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
    # The front end lives on its own origin (C-03): the exact origins, comma-separated, that may
    # change anything from a browser and that CORS answers. Empty: no browser page but the API's.
    FRONTEND_ORIGINS: str = ""

    def frontend_origins(self) -> tuple[str, ...]:
        """The listed origins, lower case and without a trailing slash."""
        return tuple(_origin(o) for o in self.FRONTEND_ORIGINS.split(",") if o.strip())

    @model_validator(mode="after")
    def _exact_frontend_origins(self) -> Self:
        for raw in (o for o in self.FRONTEND_ORIGINS.split(",") if o.strip()):
            parts = urlsplit(_origin(raw))
            exact = (
                parts.scheme in ("https", "http")
                and parts.hostname is not None
                and not parts.username
                and parts.path == ""
                and not parts.query
                and not parts.fragment
                and "*" not in parts.netloc
            )
            if not exact:
                # The value is not repeated: a wrong origin may carry what should not be logged.
                raise ValueError("FRONTEND_ORIGINS takes exact origins: scheme://host[:port]")
            if parts.scheme == "http" and (
                not _is_local(parts.hostname) or self.ENVIRONMENT is Environment.PRODUCTION
            ):
                raise ValueError("FRONTEND_ORIGINS must use https (plain http only for localhost)")
        return self

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
        database = urlsplit(self.DATABASE_URL)
        if _is_local(database.hostname):
            raise ValueError("production DATABASE_URL must not point to a local database")
        # Credentials and verdicts cross this link: the server is verified, not only encrypted
        # (quality review QA-010).
        if parse_qs(database.query).get("sslmode") != ["verify-full"]:
            raise ValueError("production DATABASE_URL must use sslmode=verify-full")
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
