"""QA-23 · the SDK side of the connector findings of the quality review.

- QA-015: a configuration check reads catalogue sources only: a schema-qualified table passes only
  if its schema is a catalogue one, whatever its name looks like; and it never reads the SQL text
  of other sessions, which carries literals of the client.
- QA-027: the size of a sample is a positive integer, or the probe is refused.
"""

import pytest

from argos_connector.config_sources import check_config_sources
from argos_connector.probes import sample_size


@pytest.mark.parametrize(
    ("statement", "dialect"),
    [
        ("SELECT dni AS value FROM public.pg_pacientes", "postgres"),
        ("SELECT nombre AS name, dni AS value FROM clinica.all_pacientes", "oracle"),
        ("SELECT username FROM hr.user_accounts", "oracle"),
    ],
)
def test_a_client_table_with_a_catalogue_like_name_is_refused(statement: str, dialect: str) -> None:
    with pytest.raises(ValueError, match="catalogue"):
        check_config_sources(statement, dialect)


@pytest.mark.parametrize(
    ("statement", "dialect"),
    [
        ("SELECT query AS value FROM pg_stat_activity", "postgres"),
        ("SELECT sql_text AS value FROM v$sql", "oracle"),
        ("SELECT text AS setting FROM sys.dm_exec_sql_text(0)", "tsql"),
    ],
)
def test_the_sql_text_of_other_sessions_is_refused(statement: str, dialect: str) -> None:
    with pytest.raises(ValueError, match="SQL text"):
        check_config_sources(statement, dialect)


@pytest.mark.parametrize(
    ("statement", "dialect"),
    [
        ("SELECT r.rolname AS role_name FROM pg_roles AS r", "postgres"),
        ("SELECT username, account_status FROM sys.dba_users", "oracle"),
        ("SELECT username FROM dba_users", "oracle"),
    ],
)
def test_catalogue_sources_still_pass(statement: str, dialect: str) -> None:
    check_config_sources(statement, dialect)


@pytest.mark.parametrize("k", [-1, 0, "abc", 2.5])
def test_a_sample_size_that_is_not_a_positive_integer_is_refused(k: object) -> None:
    with pytest.raises(ValueError, match="sample"):
        sample_size({"k": k}, default=50, max_rows=100)


def test_the_sample_size_is_capped_by_the_budget() -> None:
    assert sample_size({"k": 500}, default=50, max_rows=100) == 100
    assert sample_size({}, default=50, max_rows=100) == 50
