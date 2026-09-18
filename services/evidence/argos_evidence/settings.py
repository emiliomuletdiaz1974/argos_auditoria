"""Configuration of the evidence service (ARG-061…070), read from ARGOS_EVIDENCE_* variables.

The platform-wide settings (database, Temporal, NATS, Vault) stay in
``argos_common.config``; these are the ones only this service needs.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvidenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARGOS_EVIDENCE_", extra="ignore")

    ISSUER_DID: str
    STATUS_BASE_URL: str
    CREDENTIAL_BASE_URL: str
    VERIFIER_URL: str
    RETENTION_DAYS: int = 3650
    S3_ENDPOINT: str = "http://127.0.0.1:7075"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: SecretStr = SecretStr("")
    SIGNING_KEY: str = "argos-evidence"
    TSA_URL: str = "http://127.0.0.1:3180"
    TSA_ROOTS_FILE: str | None = None
    TSA_ROOTS_URL: str | None = None  # development only: the test TSA publishes its root
    STAMP_ATTEMPTS: int = 12
    STAMP_WAIT_SECONDS: int = 300
