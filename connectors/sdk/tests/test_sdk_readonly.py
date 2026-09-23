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


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT pg_is_in_recovery()",
        "SELECT pg_last_xact_replay_timestamp()",
        "SELECT pg_total_relation_size('clinic.patients')",
        "SELECT lower(name), coalesce(a, 0), count(*) FROM t GROUP BY 1, 2",
        "SELECT a FROM t WHERE note LIKE 'delete%'",
        "SELECT coalesce(status, 'deleted') FROM t",
    ],
)
def test_catalog_and_ordinary_functions_are_allowed(statement: str) -> None:
    validate_read_only_sql(statement, "postgres")


def test_package_qualified_functions_are_checked_by_full_name() -> None:
    with pytest.raises(ReadOnlyViolationError, match="utl_http.request"):
        validate_read_only_sql("SELECT UTL_HTTP.REQUEST('http://x') FROM dual", "oracle")


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


# ---------- evasions found by the security review (F09-02: SEC-005, SEC-006, SEC-021) ----------


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT 1 /*!, SLEEP(100) */",  # MySQL runs the body of a versioned comment
        "SELECT 1 /*!50000 , GET_LOCK('x', 10) */",
        "SELECT 1 /*M!, SLEEP(100) */",  # and MariaDB its own
        "SELECT * FROM t --1 FOR UPDATE",  # "--" without a space is not a comment in MySQL
        "SELECT 1 --1 INTO OUTFILE '/tmp/x'",
        "SELECT /*+ ORDERED */ a FROM t",  # an optimiser hint is an instruction, not a note
    ],
)
@pytest.mark.parametrize("dialect", ["mysql", "oracle", "postgres", "tsql"])
def test_comments_that_an_engine_executes_are_rejected(statement: str, dialect: str) -> None:
    with pytest.raises(ReadOnlyViolationError, match="comment"):
        validate_read_only_sql(statement, dialect)


def test_ordinary_comments_stay_harmless() -> None:
    validate_read_only_sql("SELECT a FROM t -- the table\n", "mysql")
    validate_read_only_sql("SELECT a /* column */ FROM t", "postgres")


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM t WITH (TABLOCKX, HOLDLOCK)",
        "SELECT * FROM t WITH (XLOCK)",
        "SELECT * FROM t WITH (UPDLOCK)",
        "SELECT * FROM t WITH (NOLOCK)",
        "SELECT * FROM t OPTION (MAXDOP 1)",
    ],
)
def test_table_and_query_hints_are_rejected_in_sql_server(statement: str) -> None:
    with pytest.raises(ReadOnlyViolationError, match="hint"):
        validate_read_only_sql(statement, "tsql")


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT pg_catalog.pg_terminate_backend(123)",
        "SELECT pg_catalog.pg_cancel_backend(1)",
        "SELECT pg_catalog.pg_reload_conf()",
        "SELECT pg_catalog.set_config('role', 'admin', false)",
        "SELECT pg_catalog.nextval('s')",
        "SELECT pg_catalog.pg_notify('c', 'x')",
        "SELECT pg_sleep_for('5 minutes')",
        "SELECT pg_sleep_until('2030-01-01')",
    ],
)
def test_denied_functions_cannot_hide_behind_their_schema(statement: str) -> None:
    with pytest.raises(ReadOnlyViolationError):
        validate_read_only_sql(statement, "postgres")


@pytest.mark.parametrize(
    ("statement", "dialect"),
    [
        ("SELECT pkg.f() FROM dual", "oracle"),
        ("SELECT app.audit_touch(id) FROM t", "postgres"),
        ("SELECT dbo.fn_mark(1)", "tsql"),
        ("SELECT my_function(a) FROM t", "postgres"),
    ],
)
def test_user_defined_functions_are_not_allowed(statement: str, dialect: str) -> None:
    """In Oracle a function with PRAGMA AUTONOMOUS_TRANSACTION commits inside a read-only one."""
    with pytest.raises(ReadOnlyViolationError, match="allow list"):
        validate_read_only_sql(statement, dialect)


@pytest.mark.parametrize(
    ("statement", "dialect"),
    [
        ("SELECT has_table_privilege('u', c.oid, 'SELECT') FROM pg_catalog.pg_class c", "postgres"),
        ("SELECT pg_catalog.format_type(a.atttypid, a.atttypmod) FROM pg_attribute a", "postgres"),
        ("SELECT current_database(), version()", "postgres"),
        ("SELECT SERVERPROPERTY('ProductVersion')", "tsql"),
        ("SELECT SYS_CONTEXT('USERENV', 'DB_NAME') FROM dual", "oracle"),
    ],
)
def test_catalog_functions_on_the_allow_list_still_pass(statement: str, dialect: str) -> None:
    validate_read_only_sql(statement, dialect)
