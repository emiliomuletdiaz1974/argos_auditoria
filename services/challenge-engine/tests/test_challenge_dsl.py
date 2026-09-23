"""ARG-041 · the challenge schema is the law: nothing outside it compiles."""

from pathlib import Path
from typing import Any

import jsonschema
import pytest

from argos_challenges.dsl import (
    ChallengeError,
    LintContext,
    library_challenges,
    lint_challenge,
    load_challenge_file,
    load_schema,
    parse_challenge,
)

VALID: dict[str, Any] = {
    "id": "sec-encryption-at-rest",
    "version": "1.0",
    "title": "Cifrado en reposo verificado en el almacén",
    "objective": {"obligation": "OBL-RGPD-32-1"},
    "selector": {"asset_class": "AC-stored-health-data"},
    "probe": {
        "kind": "check_config",
        "by_connector": {"rdbms.postgresql": {"params": {"check": "encryption_at_rest"}}},
    },
    "criterion": {"threshold": {"field": "rows.0.data_checksums", "operator": "==", "value": "on"}},
    "evidence": {
        "capture": ["configuration"],
        "minimisation": "Solo parámetros de cifrado; ninguna clave ni dato de negocio.",
    },
    "severity": "critical",
}


def _spec(**changes: Any) -> dict[str, Any]:
    document = {**VALID, **changes}
    return document


def test_the_schema_itself_is_valid() -> None:
    jsonschema.Draft202012Validator.check_schema(load_schema())


def test_a_valid_challenge_parses_into_a_frozen_spec() -> None:
    spec = parse_challenge(VALID)
    assert (spec.id, spec.version, spec.severity) == ("sec-encryption-at-rest", "1.0", "critical")
    assert spec.obligation == "OBL-RGPD-32-1"
    assert spec.asset_class == "AC-stored-health-data"
    assert spec.probe_kind == "check_config"
    assert spec.sampling is None and spec.approval_required is False
    with pytest.raises(AttributeError):
        spec.id = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": "SEC-Encryption"}, "id"),
        ({"version": "1"}, "version"),
        ({"severity": "critica"}, "severity"),
        ({"probe": {"kind": "dump_table"}}, "kind"),
        ({"criterion": {"threshold": {"field": "a", "operator": "~=", "value": 1}}}, "operator"),
        ({"criterion": {}}, "criterion"),
        ({"evidence": {"capture": ["counts"], "minimisation": "corto"}}, "minimisation"),
        ({"evidence": {"capture": ["recuentos"], "minimisation": "x" * 30}}, "capture"),
        ({"extra": 1}, "extra"),
        ({"objective": {"obligation": "RGPD-5"}}, "obligation"),
    ],
)
def test_documents_outside_the_schema_are_rejected(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ChallengeError, match=message):
        parse_challenge(_spec(**changes))


def test_text_templates_are_not_a_way_to_pass_parameters() -> None:
    probe = {
        "kind": "count",
        "by_connector": {"rdbms.postgresql": {"statement": "SELECT count(*) FROM {{nodo.tabla}}"}},
    }
    with pytest.raises(ChallengeError):
        parse_challenge(_spec(probe=probe))


def test_typed_parameters_are_accepted() -> None:
    probe = {
        "kind": "count",
        "by_connector": {
            "rdbms.postgresql": {
                "statement": "SELECT count(*) FROM :table WHERE created_at < :limit",
                "params": {
                    "binds": {
                        "table": {"$node": "qualified_name"},
                        "limit": {"$campaign": "retention_limit"},
                    }
                },
            }
        },
    }
    spec = parse_challenge(_spec(probe=probe))
    assert spec.by_connector["rdbms.postgresql"]["params"]["binds"]["table"] == {
        "$node": "qualified_name"
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"probe": {"kind": "sample", "params": {"columns": ["dni"]}}}, "approval"),
        (
            {
                "evidence": {
                    "capture": ["hashed_sample"],
                    "minimisation": "Solo digests de la muestra, nunca valores.",
                },
                "approval_required": True,
            },
            "hashed_sample",
        ),
        ({"objective": {"obligation": "OBL-RGPD-99-9"}}, "obligation"),
        ({"selector": {"asset_class": "AC-does-not-exist"}}, "asset class"),
        ({"criterion": {"opa": {"package": "argos.unknown"}}}, "package"),
        ({"id": "sec-other-name"}, "file"),
    ],
)
def test_the_extra_rules_reject_what_the_schema_cannot(
    changes: dict[str, Any], message: str
) -> None:
    context = LintContext.from_library()
    spec = parse_challenge(_spec(**changes))
    errors = lint_challenge(spec, context, path=Path("sec-encryption-at-rest.yaml"))
    assert any(message in error for error in errors), errors


def test_the_shipped_challenges_pass_the_schema_and_the_rules() -> None:
    context = LintContext.from_library()
    paths = library_challenges()
    assert len(paths) >= 2
    for path in paths:
        assert lint_challenge(load_challenge_file(path), context) == [], path


def test_an_opa_input_may_not_declare_the_evidence() -> None:
    """SEC-012: `out_of_term: 0` in a challenge would absolve without looking."""
    from dataclasses import replace

    from argos_challenges.dsl import intrinsic_errors
    from argos_challenges.library.catalog import load_library

    spec = next(iter(load_library().values()))
    forged = replace(
        spec,
        criterion={"opa": {"package": "argos.retention", "input_map": {"out_of_term": 0}}},
    )
    assert any("out_of_term" in e for e in intrinsic_errors(forged))
    unsampled = replace(spec, probe_kind="sample", approval_required=False)
    assert any("approval_required" in e for e in intrinsic_errors(unsampled))


@pytest.mark.parametrize(
    ("connector", "statement", "refused"),
    [
        ("rdbms.postgresql", "SELECT dni, diagnostico FROM pacientes", True),
        ("rdbms.generic", "SELECT amount FROM billing.invoices", True),
        ("rdbms.postgresql", "SELECT setting FROM pg_settings WHERE name = 'ssl'", False),
    ],
)
def test_a_check_config_reads_configuration_not_business_tables(
    connector: str, statement: str, refused: bool
) -> None:
    """SEC-022: the lint refuses a challenge that would bring a table of the client as evidence."""
    from argos_challenges.dsl import intrinsic_errors

    probe = {"kind": "check_config", "by_connector": {connector: {"statement": statement}}}
    errors = intrinsic_errors(parse_challenge(_spec(probe=probe)))
    assert any("configuration" in e for e in errors) is refused
