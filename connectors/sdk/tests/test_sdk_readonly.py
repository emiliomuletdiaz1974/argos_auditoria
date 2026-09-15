"""Syntactic read-only guard (ARG-011): every write path is rejected in every dialect."""

import pytest

from argos_common.errors import ReadOnlyViolationError
from argos_connector.readonly import assert_safe_http_method, validate_read_only_sql
from argos_connector.testing import HTTP_WRITE_METHODS, SQL_WRITE_ATTEMPTS

DIALECTS = ("postgres", "mysql", "tsql", "oracle", "sqlite")
PORTABLE_READS = (
    "SELECT COUNT(*) AS n FROM clinic.patients WHERE created_at < :cutoff",
    "select name, setting from pg_settings",
    "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
    "SELECT a FROM t UNION SELECT b FROM u",
    "SELECT a FROM t FETCH FIRST 100 ROWS ONLY",
    "SELECT 1;",
)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("statement", SQL_WRITE_ATTEMPTS)
def test_write_attempts_are_rejected(statement: str, dialect: str) -> None:
    with pytest.raises(ReadOnlyViolationError):
        validate_read_only_sql(statement, dialect)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("statement", PORTABLE_READS)
def test_reads_are_allowed(statement: str, dialect: str) -> None:
    validate_read_only_sql(statement, dialect)


def test_dialect_specific_reads() -> None:
    validate_read_only_sql("SELECT TOP 100 a FROM dbo.t", "tsql")
    validate_read_only_sql("SHOW TABLES", "mysql")
    validate_read_only_sql("DESCRIBE t", "mysql")


@pytest.mark.parametrize("statement", ["", "   ", "\n"])
def test_empty_statement_is_rejected(statement: str) -> None:
    with pytest.raises(ReadOnlyViolationError, match="empty"):
        validate_read_only_sql(statement, "postgres")


def test_side_effect_functions_are_rejected() -> None:
    with pytest.raises(ReadOnlyViolationError):
        validate_read_only_sql("SELECT set_config('role', 'admin', false)", "postgres")
    with pytest.raises(ReadOnlyViolationError):
        validate_read_only_sql("SELECT dbms_lock.sleep(5) FROM dual", "oracle")


def test_unparseable_statement_is_rejected() -> None:
    with pytest.raises(ReadOnlyViolationError):
        validate_read_only_sql("SELECT FROM WHERE )(", "postgres")


@pytest.mark.parametrize("method", HTTP_WRITE_METHODS)
def test_unsafe_http_methods_are_rejected(method: str) -> None:
    with pytest.raises(ReadOnlyViolationError):
        assert_safe_http_method(method)


@pytest.mark.parametrize("method", ["GET", "head", "Options"])
def test_safe_http_methods_are_normalised(method: str) -> None:
    assert assert_safe_http_method(method) == method.upper()
