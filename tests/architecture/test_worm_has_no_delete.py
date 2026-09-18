"""ARG-061 · the WORM client has no way to delete: not by name, not by a dynamic attribute."""

import ast
import re
from pathlib import Path

import argos_evidence.worm as worm
from argos_evidence.worm import WormStore

SOURCE = Path(worm.__file__)
FORBIDDEN = re.compile(r"delete|remove|purge|erase|destroy|expire|lifecycle", re.IGNORECASE)
DYNAMIC = {"getattr", "setattr", "eval", "exec", "__import__", "globals", "locals", "vars"}


def _tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def test_the_store_exposes_only_writing_once_and_reading() -> None:
    public = {name for name in dir(WormStore) if not name.startswith("_")}
    assert public == {"get", "put_immutable", "retention"}


def test_no_attribute_name_or_string_can_reach_a_delete_call() -> None:
    offenders = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Attribute) and FORBIDDEN.search(node.attr):
            offenders.append(f"attribute {node.attr} (line {node.lineno})")
        elif isinstance(node, ast.Name) and FORBIDDEN.search(node.id):
            offenders.append(f"name {node.id} (line {node.lineno})")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and FORBIDDEN.search(node.value)
            and not _is_docstring(node)
        ):
            offenders.append(f"string {node.value!r} (line {node.lineno})")
    assert offenders == []


def test_no_dynamic_attribute_access() -> None:
    calls = [
        node.func.id
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert DYNAMIC.isdisjoint(calls)


def _is_docstring(node: ast.Constant) -> bool:
    for parent in ast.walk(_tree()):
        body = getattr(parent, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            value = body[0].value
            if isinstance(value, ast.Constant) and value.lineno == node.lineno:
                return True
    return False
