"""Graph write performance · hot queries never walk variable-length paths (pure).

AGE 1.5.0 turns a variable-length traversal from a System into a scan that grows with the whole
graph (1.5 s per system with 10 200 columns); the same questions asked per label with the indexed
`system_id` property stay in milliseconds (task F03-15).
"""

import importlib
import pkgutil
import re

import argos_inventory
from argos_inventory.versioning import deltas

VARIABLE_LENGTH = re.compile(r"\[[^\]]*\*[^\]]*\]")


def _inventory_queries() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for module_info in pkgutil.walk_packages(argos_inventory.__path__, "argos_inventory."):
        if module_info.name.endswith((".main", ".worker", ".benchmark")):
            continue
        module = importlib.import_module(module_info.name)
        for name, value in vars(module).items():
            texts = value.values() if isinstance(value, dict) else [value]
            for text in texts:
                if isinstance(text, str) and "MATCH" in text:
                    found.append((f"{module_info.name}.{name}", text))
    return found


def test_the_inventory_has_graph_queries_to_check() -> None:
    assert len(_inventory_queries()) > 20


def test_inventory_queries_have_no_variable_length_paths() -> None:
    offending = [name for name, text in _inventory_queries() if VARIABLE_LENGTH.search(text)]
    assert offending == []


def test_deltas_cover_every_label_a_system_contains() -> None:
    expected = {"Schema", "Table", "Column", "FileArea"}
    assert set(deltas.APPEARED_BY_LABEL) == expected
    assert set(deltas.DISAPPEARED_BY_LABEL) == expected
    assert set(deltas.MARK_MISSING_BY_LABEL) == expected


def test_mark_missing_always_names_the_label() -> None:
    for label, query in deltas.MARK_MISSING_BY_LABEL.items():
        assert f"(n:{label} {{key: k}})" in query
