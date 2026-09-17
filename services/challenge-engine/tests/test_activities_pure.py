"""ARG-044 · minimisation and the closed list of internal questions."""

from typing import Any

import pytest

from argos_challenges.probes import CAPTURE_KEYS, INVENTORY_QUERIES, minimise, probe_spec

RESULT: dict[str, Any] = {
    "count": 12,
    "rows": [{"ssl": "off"}],
    "cell_digests": [["d1"]],
    "columns": ["dni_number"],
    "dsn": "postgresql://user:password@host/db",
    "sample_values": ["12345678Z"],
}


def test_only_the_declared_captures_leave_the_probe() -> None:
    assert minimise(RESULT, ["counts"]) == {"count": 12}
    assert minimise(RESULT, ["configuration"]) == {"rows": [{"ssl": "off"}]}
    assert minimise(RESULT, ["counts", "hashes"]) == {"count": 12, "cell_digests": [["d1"]]}


@pytest.mark.parametrize("capture", [[], ["result"], ["counts"], ["configuration"], ["hashes"]])
def test_values_and_connection_strings_never_leave(capture: list[str]) -> None:
    minimised = minimise(RESULT, capture)
    assert "dsn" not in minimised and "sample_values" not in minimised


def test_an_undeclared_capture_lets_nothing_through() -> None:
    assert minimise(RESULT, ["everything"]) == {}
    assert set(CAPTURE_KEYS) == {"result", "counts", "hashes", "configuration", "hashed_sample"}


def test_the_evidence_block_can_be_passed_as_it_is() -> None:
    evidence = {"capture": ["counts"], "minimisation": "Solo recuentos."}
    assert minimise(RESULT, evidence) == {"count": 12}


def test_a_probe_spec_travels_with_its_parameters_and_never_with_templates() -> None:
    unit = {
        "probe": {
            "kind": "count",
            "target": "clinic.patients",
            "statement": "SELECT count(*) FROM clinic.patients WHERE created_at < :limit",
            "params": {"binds": {"limit": "2011-09-18"}},
        }
    }
    spec = probe_spec(unit)
    assert spec.kind == "count" and spec.target == "clinic.patients"
    assert spec.params["binds"] == {"limit": "2011-09-18"}
    assert spec.statement is not None and "{{" not in spec.statement


def test_the_internal_questions_are_a_closed_read_only_list() -> None:
    assert set(INVENTORY_QUERIES) == {
        "unclassified_columns",
        "pending_ai_systems",
        "prohibited_ai_systems",
    }
    for statement in INVENTORY_QUERIES.values():
        lowered = statement.lower()
        assert lowered.startswith("select ")
        assert not any(word in lowered for word in ("insert", "update", "delete", "truncate"))
