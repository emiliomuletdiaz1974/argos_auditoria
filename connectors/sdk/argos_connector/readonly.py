"""Syntactic read-only guard for declared statements (ARG-011, second line of defence).

The customer's read-only account (first line) and the read-only session opened by each
connector (third line) remain mandatory: this guard never replaces them.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from argos_common.errors import ReadOnlyViolationError

SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = tuple(
    node
    for node in (
        exp.Select,
        exp.Union,
        exp.Intersect,
        exp.Except,
        getattr(exp, "Describe", None),
        getattr(exp, "Show", None),
    )
    if node is not None
)
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Create",
        "Drop",
        "Alter",
        "AlterTable",
        "Command",
        "TruncateTable",
        "Into",
        "Copy",
        "Lock",
        "Transaction",
        "Commit",
        "Rollback",
        "Set",
        "Use",
        "Grant",
        "Revoke",
        "Pragma",
        "LoadData",
        "Kill",
        "Analyze",
    )
    if hasattr(exp, name)
)
DENIED_FUNCTIONS = frozenset(
    {
        "nextval",
        "setval",
        "set_config",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_sleep",
        "lo_import",
        "lo_export",
        "lo_unlink",
        "dblink_exec",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "xp_cmdshell",
        "sleep",
        "benchmark",
        "get_lock",
        "load_file",
    }
)


def _function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def validate_read_only_sql(statement: str, dialect: str) -> None:
    if not statement.strip():
        raise ReadOnlyViolationError("empty statement")
    try:
        trees = [tree for tree in sqlglot.parse(statement, read=dialect) if tree is not None]
    except ParseError:
        raise ReadOnlyViolationError("statement is not parseable as read-only SQL") from None
    if len(trees) != 1:
        raise ReadOnlyViolationError(f"exactly one statement is allowed, got {len(trees)}")
    root = trees[0]
    if not isinstance(root, _ALLOWED_ROOTS):
        raise ReadOnlyViolationError(f"statement type not allowed: {type(root).__name__}")
    for item in root.walk():
        node = item[0] if isinstance(item, tuple) else item
        if isinstance(node, _FORBIDDEN_NODES):
            raise ReadOnlyViolationError(f"forbidden construct: {type(node).__name__}")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if name in DENIED_FUNCTIONS or name.startswith("dbms_"):
                raise ReadOnlyViolationError(f"function with side effects: {name}")


def assert_safe_http_method(method: str) -> str:
    normalised = method.upper()
    if normalised not in SAFE_HTTP_METHODS:
        raise ReadOnlyViolationError(f"unsafe HTTP method: {normalised}")
    return normalised
