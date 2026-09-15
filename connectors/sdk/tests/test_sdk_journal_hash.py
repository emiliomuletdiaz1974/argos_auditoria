"""Statement normalisation for the prior query journal (ARG-012)."""

import pytest

from argos_connector.journal import QueryJournal, statement_hash


def test_hash_ignores_case_and_whitespace() -> None:
    assert statement_hash("  SELECT  count(*)\n FROM t ") == statement_hash(
        "select count(*) from t"
    )
    assert len(statement_hash("select 1")) == 32


def test_missing_statement_hashes_as_empty() -> None:
    assert statement_hash(None) == statement_hash("")


def test_system_id_must_be_a_uuid() -> None:
    with pytest.raises(ValueError):
        QueryJournal("postgresql://unused", "not-a-uuid")
