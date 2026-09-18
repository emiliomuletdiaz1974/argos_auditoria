"""Wiring of the evidence service from its configuration (ARG-061…070)."""

from __future__ import annotations

from pathlib import Path

import boto3
import httpx

from argos_common.config import ArgosConfig
from argos_common.release import VaultTransitSigner
from argos_evidence.activities import EvidenceActivities
from argos_evidence.settings import EvidenceSettings
from argos_evidence.tsa import http_transport
from argos_evidence.worm import WormStore, ensure_buckets


def tsa_roots(settings: EvidenceSettings) -> list[str]:
    """The TSA roots to trust: a file in the appliance, the test TSA's own root in development."""
    if settings.TSA_ROOTS_FILE:
        return [Path(settings.TSA_ROOTS_FILE).read_text(encoding="utf-8")]
    if settings.TSA_ROOTS_URL:
        response = httpx.get(settings.TSA_ROOTS_URL, timeout=10)
        response.raise_for_status()
        return [response.text]
    raise ValueError("configure ARGOS_EVIDENCE_TSA_ROOTS_FILE (or TSA_ROOTS_URL in development)")


def build_activities(config: ArgosConfig, settings: EvidenceSettings) -> EvidenceActivities:
    client = boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY.get_secret_value(),
        region_name="us-east-1",
    )
    ensure_buckets(client, default_retention_days=settings.RETENTION_DAYS)
    token = config.VAULT_TOKEN.get_secret_value() if config.VAULT_TOKEN else ""
    signer = VaultTransitSigner(config.VAULT_ADDR, token, key=settings.SIGNING_KEY)
    return EvidenceActivities(
        config.DATABASE_URL,
        WormStore(client),
        signer,
        settings,
        http_transport(settings.TSA_URL),
        tsa_roots(settings),
    )
