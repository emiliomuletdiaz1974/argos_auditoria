"""Daily budget per service, and the gateway wired to PostgreSQL (ARG-052).

The quota lives in a table because it is an operational decision, not a constant: an appliance
under pressure moves the nightly classification budget without a release. What never moves is that
the budget is read **before** calling the model.
"""

from collections.abc import Mapping
from typing import Any

import psycopg

from argos_ai.backends.base import Backend
from argos_ai.gateway import Gateway
from argos_common.journal_pg import PostgresJournal

_QUOTAS = "SELECT service, daily_tokens FROM argos.ai_quotas"
_SPENT = (
    "SELECT service, coalesce(sum(tokens_in + tokens_out), 0)::bigint FROM argos.ai_usage "
    "WHERE created_at >= date_trunc('day', now()) GROUP BY service"
)
_RECORD = (
    "INSERT INTO argos.ai_usage (service, model, prompt_sha256, tokens_in, tokens_out) "
    "VALUES (%(service)s, %(model)s, %(prompt_sha256)s, %(tokens_in)s, %(tokens_out)s)"
)
ACTOR = "system:ai-gateway"


def daily_quotas(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn) as conn:
        return {str(row[0]): int(row[1]) for row in conn.execute(_QUOTAS).fetchall()}


def spent_today(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn) as conn:
        return {str(row[0]): int(row[1]) for row in conn.execute(_SPENT).fetchall()}


def record_usage(dsn: str, row: Mapping[str, Any]) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(_RECORD, dict(row))


def postgres_gateway(
    dsn: str, backend: Backend, model: str = "argos-llm", **kwargs: Any
) -> Gateway:
    """The gateway as the appliance runs it: quota from the table, log in the journal."""
    journal = PostgresJournal(dsn)

    def append(entry: dict[str, Any]) -> None:
        action = str(entry.pop("action"))
        journal.append(ACTOR, action, entry)

    return Gateway(
        backend,
        journal=append,
        usage=lambda row: record_usage(dsn, row),
        quotas=daily_quotas(dsn),
        spent=spent_today(dsn),
        model=model,
        **kwargs,
    )
