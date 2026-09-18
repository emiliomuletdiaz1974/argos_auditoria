"""ARG-056 · the generator goes through the real gateway, quota and journal included (F06-09)."""

import asyncio
import json

import psycopg
import pytest
from argos_ai.backends.fake import FakeBackend
from argos_ai.generate.challenge_gen import propose_challenge
from argos_ai.quotas import postgres_gateway

from argos_challenges.dsl import LintContext
from argos_ontology.vocabulary import LIBRARY_DIR

pytestmark = pytest.mark.integration

VALID = (LIBRARY_DIR / "challenges" / "sec" / "sec-encryption-in-transit.yaml").read_text(
    encoding="utf-8"
)


def test_a_generated_proposal_spends_the_quota_of_the_challenge_service(migrated_db: str) -> None:
    gateway = postgres_gateway(migrated_db, FakeBackend.of([json.dumps({"yaml": VALID})]))
    proposal = asyncio.run(
        propose_challenge(
            "OBL-RGPD-32-3", "Cifrado en tránsito.", gateway, LintContext.from_library()
        )
    )
    assert proposal.valid
    with psycopg.connect(migrated_db) as conn:
        services = [row[0] for row in conn.execute("SELECT service FROM argos.ai_usage")]
    assert services == ["challenge"]


def test_a_proposal_that_writes_is_stopped_before_it_is_logged_as_good(migrated_db: str) -> None:
    """The guardrail refuses it at the gateway: no usage row is written for a rejected answer."""
    writes = VALID.replace("SELECT setting FROM pg_settings WHERE name = 'ssl'", "DROP TABLE x")
    gateway = postgres_gateway(migrated_db, FakeBackend.of([json.dumps({"yaml": writes})]))
    proposal = asyncio.run(
        propose_challenge(
            "OBL-RGPD-32-3", "Cifrado en tránsito.", gateway, LintContext.from_library()
        )
    )
    assert not proposal.valid
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute("SELECT count(*) FROM argos.ai_usage").fetchone() == (0,)
