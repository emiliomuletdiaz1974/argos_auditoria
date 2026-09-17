"""ARG-042 · the compiler turns the applicability plan into inert, auditable work units."""

from typing import Any

import pytest

from argos_challenges.compiler import (
    CONNECTOR_IDS,
    CompilerError,
    compile_campaign,
    connector_id,
    unit_id,
)
from argos_challenges.dsl import parse_challenge

CAMPAIGN = "01920000-0000-7000-8000-0000000000c1"
POSTGRES = "01920000-0000-7000-8000-00000000a001"
FILES = "01920000-0000-7000-8000-00000000b002"
SYSTEMS: dict[str, dict[str, Any]] = {
    POSTGRES: {
        "id": POSTGRES,
        "name": "dev-source-postgres",
        "kind": "rdbms",
        "connector": "argos_sql.postgres:PostgresConnector",
        "config": {},
    },
    FILES: {
        "id": FILES,
        "name": "dev-files-smb",
        "kind": "files",
        "connector": "argos_files.connector:FilesConnector",
        "config": {"protocol": "smb"},
    },
}
NODES: dict[str, dict[str, Any]] = {
    "k-col-1": {
        "node_key": "k-col-1",
        "label": "Column",
        "name": "created_at",
        "qualified_name": "clinic.patients.created_at",
        "system_id": POSTGRES,
        "categories": [{"category": "personal_data", "confidence": "0.6000"}],
    },
    "k-area-1": {
        "node_key": "k-area-1",
        "label": "FileArea",
        "name": "share",
        "qualified_name": "smb://share",
        "system_id": FILES,
        "categories": [],
    },
}
CHALLENGE = parse_challenge(
    {
        "id": "ret-table-retention",
        "version": "1.0",
        "title": "Retención efectiva frente al calendario declarado",
        "objective": {"obligation": "OBL-RGPD-5-1"},
        "selector": {"asset_class": "AC-stored-personal-data"},
        "probe": {
            "kind": "count",
            "by_connector": {
                "rdbms.postgresql": {
                    "statement": "SELECT count(*) FROM :table WHERE :column < :limit",
                    "params": {
                        "binds": {
                            "table": {"$node": "qualified_name"},
                            "column": {"$node": "name"},
                            "limit": {"$campaign": "retention_limit"},
                            "treatment": {"$client": "treatment_id"},
                        }
                    },
                }
            },
        },
        "criterion": {"opa": {"package": "argos.retention"}},
        "evidence": {
            "capture": ["counts"],
            "minimisation": "Solo el recuento de registros fuera de plazo y sus parámetros.",
        },
        "severity": "high",
    }
)
PLAN = [
    {
        "obligation": "OBL-RGPD-5-1",
        "challenge_id": "ret-table-retention",
        "node_keys": ["k-col-1"],
    }
]
CONTEXT = {"client": {"treatment_id": "T-HIS"}, "campaign": {"retention_limit": "2011-09-18"}}


def _compile(**changes: Any) -> Any:
    arguments: dict[str, Any] = {
        "campaign_id": CAMPAIGN,
        "plan": PLAN,
        "challenges": {CHALLENGE.id: CHALLENGE},
        "nodes": NODES,
        "systems": SYSTEMS,
        "context": CONTEXT,
    }
    arguments.update(changes)
    return compile_campaign(**arguments)


def test_every_registered_connector_has_an_identifier() -> None:
    assert connector_id(SYSTEMS[POSTGRES]) == "rdbms.postgresql"
    assert connector_id(SYSTEMS[FILES]) == "files.smb"
    assert set(CONNECTOR_IDS) >= {
        "argos_sql.postgres:PostgresConnector",
        "argos_sql.generic:SqlConnector",
        "argos_files.connector:FilesConnector",
    }


def test_a_unit_carries_everything_needed_to_run_and_to_explain_itself() -> None:
    compiled = _compile()
    [unit] = compiled.units
    assert unit["challenge_id"] == "ret-table-retention"
    assert unit["obligation"] == "OBL-RGPD-5-1"
    assert unit["system_id"] == POSTGRES
    assert unit["node_key"] == "k-col-1"
    assert unit["severity"] == "high"
    assert unit["criterion"] == {"opa": {"package": "argos.retention"}}
    assert unit["evidence"]["capture"] == ["counts"]
    assert unit["unit_id"] == unit_id(CAMPAIGN, "ret-table-retention", "1.0", "k-col-1")
    assert compiled.unverifiable == []


def test_the_typed_parameters_are_resolved_to_values() -> None:
    [unit] = _compile().units
    binds = unit["probe"]["params"]["binds"]
    assert binds == {
        "table": "clinic.patients.created_at",
        "column": "created_at",
        "limit": "2011-09-18",
        "treatment": "T-HIS",
    }
    assert unit["probe"]["target"] == "clinic.patients.created_at"
    assert "{{" not in unit["probe"]["statement"]


def test_the_same_inputs_give_the_same_units_in_the_same_order() -> None:
    first = _compile().units
    second = _compile().units
    assert first == second


def test_a_node_of_a_connector_without_a_variant_is_unverifiable_not_silent() -> None:
    plan = [
        {
            "obligation": "OBL-RGPD-5-1",
            "challenge_id": "ret-table-retention",
            "node_keys": ["k-col-1", "k-area-1"],
        }
    ]
    compiled = _compile(plan=plan)
    assert [unit["node_key"] for unit in compiled.units] == ["k-col-1"]
    assert compiled.unverifiable == [
        {
            "challenge_id": "ret-table-retention",
            "connector": "files.smb",
            "node_key": "k-area-1",
            "reason": "the challenge has no probe variant for this connector",
            "system_id": FILES,
        }
    ]


def test_a_missing_reference_is_an_error_not_an_empty_value() -> None:
    with pytest.raises(CompilerError, match="retention_limit"):
        _compile(context={"client": {"treatment_id": "T-HIS"}, "campaign": {}})
    with pytest.raises(CompilerError, match="qualified_name"):
        without_name: dict[str, Any] = {**NODES["k-col-1"], "qualified_name": None, "name": None}
        nodes = {"k-col-1": without_name}
        _compile(nodes=nodes)


def test_a_plan_row_without_its_challenge_or_node_is_an_error() -> None:
    with pytest.raises(CompilerError, match="unknown challenge"):
        _compile(plan=[{**PLAN[0], "challenge_id": "sec-unknown"}])


def test_a_challenge_reserved_but_not_written_yet_is_unverifiable() -> None:
    plan = [{**PLAN[0], "challenge_id": "sec-not-written-yet"}]
    compiled = _compile(plan=plan, reserved=frozenset({"sec-not-written-yet"}))
    assert compiled.units == []
    assert compiled.unverifiable[0]["reason"].endswith("not written yet")
    with pytest.raises(CompilerError, match="unknown node"):
        _compile(plan=[{**PLAN[0], "node_keys": ["k-none"]}])


def test_a_sample_probe_marks_the_unit_as_needing_approval() -> None:
    sampling_challenge = parse_challenge(
        {
            "id": "dsr-access-request-term",
            "version": "1.0",
            "title": "Solicitud de acceso respondida dentro de plazo",
            "objective": {"obligation": "OBL-RGPD-15-1"},
            "selector": {"asset_class": "AC-stored-personal-data"},
            "probe": {
                "kind": "sample",
                "by_connector": {"rdbms.postgresql": {"params": {"columns": ["dni_number"]}}},
            },
            "criterion": {"threshold": {"field": "n", "operator": ">=", "value": 1}},
            "evidence": {
                "capture": ["hashed_sample"],
                "minimisation": "Solo digests de la muestra, nunca valores en claro.",
            },
            "severity": "high",
            "approval_required": True,
            "preconditions": ["synthetic_subject_injected"],
        }
    )
    plan = [
        {
            "obligation": "OBL-RGPD-15-1",
            "challenge_id": "dsr-access-request-term",
            "node_keys": ["k-col-1"],
        }
    ]
    [unit] = _compile(plan=plan, challenges={sampling_challenge.id: sampling_challenge}).units
    assert unit["needs_approval"] is True
    assert unit["preconditions"] == ["synthetic_subject_injected"]
