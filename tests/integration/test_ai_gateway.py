"""ARG-052 · the gateway against a real database: quota from the table, log in the journal."""

import asyncio
import json
from typing import Any

import psycopg
import pytest
from argos_ai.backends.fake import FakeBackend
from argos_ai.gateway import QuotaExceededError
from argos_ai.quotas import daily_quotas, postgres_gateway, spent_today

from argos_common.journal_pg import PostgresJournal

pytestmark = pytest.mark.integration

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["category"],
    "properties": {"category": {"type": "string"}},
}
SYSTEM = "Clasifica la columna."
USER = "columna: clinic.patients.national_id con el valor 99992001F"


def test_the_quotas_come_from_the_table(migrated_db: str) -> None:
    quotas = daily_quotas(migrated_db)
    assert quotas["assistant"] > quotas["reports"] > 0
    assert spent_today(migrated_db) == {}


def test_a_completion_writes_its_usage_and_its_journal_entry(migrated_db: str) -> None:
    gateway = postgres_gateway(migrated_db, FakeBackend.of(['{"category": "official_identifier"}']))
    answer = asyncio.run(gateway.chat_json("inventory", SYSTEM, USER, SCHEMA))

    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute(
            "SELECT service, prompt_sha256, tokens_in FROM argos.ai_usage"
        ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [("inventory", answer.prompt_sha256)]
    assert spent_today(migrated_db)["inventory"] > 0

    entries = [e for e in PostgresJournal(migrated_db).read(1, 100) if e.action == "ai.completion"]
    assert entries and entries[-1].actor == "system:ai-gateway"
    assert answer.prompt_sha256 in entries[-1].payload_canon


def test_neither_the_prompt_nor_the_personal_datum_is_ever_written(migrated_db: str) -> None:
    """The value travels scrubbed to the model and does not reach the log in any form."""
    gateway = postgres_gateway(migrated_db, FakeBackend.of(['{"category": "official_identifier"}']))
    answer = asyncio.run(gateway.chat_json("inventory", SYSTEM, USER, SCHEMA))
    assert answer.substitutions == 1

    with psycopg.connect(migrated_db) as conn:
        usage = conn.execute("SELECT to_jsonb(u) FROM argos.ai_usage u").fetchall()
    entries = [e.payload_canon for e in PostgresJournal(migrated_db).read(1, 100)]
    written = json.dumps([row[0] for row in usage], ensure_ascii=False) + "".join(entries)
    assert "99992001F" not in written
    assert USER not in written and SYSTEM not in written


def test_a_service_with_no_row_in_the_table_cannot_spend(migrated_db: str) -> None:
    """The default is zero, not infinite: a new service declares its budget or waits."""
    gateway = postgres_gateway(migrated_db, FakeBackend.of(['{"category": "personal_data"}']))
    with pytest.raises(QuotaExceededError):
        asyncio.run(gateway.chat_json("brand-new-service", SYSTEM, USER, SCHEMA))


def test_what_was_spent_today_is_carried_into_the_next_gateway(migrated_db: str) -> None:
    """A restart does not hand the service a fresh budget."""
    first = postgres_gateway(migrated_db, FakeBackend.of(['{"category": "personal_data"}']))
    asyncio.run(first.chat_json("reports", SYSTEM, USER, SCHEMA))
    spent = spent_today(migrated_db)["reports"]

    with psycopg.connect(migrated_db) as conn:
        conn.execute(
            "UPDATE argos.ai_quotas SET daily_tokens = %s WHERE service = 'reports'", (spent,)
        )
    second = postgres_gateway(migrated_db, FakeBackend.of(['{"category": "personal_data"}']))
    with pytest.raises(QuotaExceededError):
        asyncio.run(second.chat_json("reports", SYSTEM, USER, SCHEMA))


def test_the_gateway_works_under_the_restricted_role(migrated_db: str) -> None:
    """The container connects as `argos_ai`, not as the owner: quota, usage and journal must all
    work with the privileges of the barrier (F06-01), and nothing more."""
    restricted = f"{migrated_db}?options=-c%20role%3Dargos_ai"
    gateway = postgres_gateway(restricted, FakeBackend.of(['{"category": "personal_data"}']))
    answer = asyncio.run(gateway.chat_json("inventory", SYSTEM, USER, SCHEMA))
    with psycopg.connect(restricted) as conn:
        assert conn.execute("SELECT current_user").fetchone() == ("argos_ai",)
        rows = conn.execute("SELECT prompt_sha256 FROM argos.ai_usage").fetchall()
    assert rows == [(answer.prompt_sha256,)]
