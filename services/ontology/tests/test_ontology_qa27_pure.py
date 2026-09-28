"""QA-27 · the ontology at its edges (quality review QA-036, 037, 038).

- QA-036: the fingerprint of the library does not depend on the operating system.
- QA-037: an ODRL constraint whose operator ARGOS does not translate, or a clause it does not
  verify, becomes an unverifiable finding, never a challenge with the opposite meaning.
- QA-038: a date with a time is not a date; a date that cannot be read is an error, not a rule
  that applies for ever.
"""

from datetime import date, datetime
from pathlib import Path

import pytest
from rdflib import XSD, Literal

from argos_ontology.editorial.compiler import parse_obligation
from argos_ontology.library_hash import library_files
from argos_ontology.odrl import parse_policy, to_challenges
from argos_ontology.resolver import in_force
from argos_ontology.vocabulary import LIBRARY_DIR


def test_the_library_is_hashed_in_the_order_of_its_posix_paths() -> None:
    files = library_files()
    posix = [p.relative_to(LIBRARY_DIR).as_posix() for p in files]
    assert posix == sorted(posix)


def _policy(**rules: object) -> dict[str, object]:
    return {"uid": "urn:policy:1", "target": "urn:asset:1", **rules}


def _templates(policy: dict[str, object]) -> dict[str, dict[str, object]]:
    return {spec["template"]: spec["params"] for spec in to_challenges(parse_policy(policy))}


def test_a_purpose_that_is_excluded_is_not_turned_into_an_allowed_one() -> None:
    specs = _templates(_policy(permission=[{"action": "use", "constraint": [
        {"leftOperand": "purpose", "operator": "neq", "rightOperand": "marketing"}]}]))  # fmt: skip
    assert "ds-usage-purpose" not in specs
    clauses = specs["ds-unverifiable"]["clauses"]
    assert isinstance(clauses, list) and any("purpose" in c for c in clauses)


def test_a_minimum_retention_is_not_turned_into_a_maximum() -> None:
    specs = _templates(_policy(obligation=[{"action": "delete", "constraint": [
        {"leftOperand": "elapsedTime", "operator": "gteq", "rightOperand": "P5Y"}]}]))  # fmt: skip
    assert "ds-asset-retention" not in specs
    assert "ds-unverifiable" in specs


@pytest.mark.parametrize(
    "rule",
    [
        {"permission": [{"action": "use", "constraint": [
            {"leftOperand": "spatial", "operator": "eq", "rightOperand": "EU"}]}]},
        {"obligation": [{"action": "notify"}]},
        {"prohibition": [{"action": "sell"}]},
    ],
)  # fmt: skip
def test_a_clause_argos_does_not_verify_is_said_to_be_unverifiable(rule: dict[str, object]) -> None:
    assert "ds-unverifiable" in _templates(_policy(**rule))


def test_a_date_with_a_time_is_not_an_in_force_date() -> None:
    document = {
        "id": "OBL-RGPD-5-1", "norm": "RGPD", "article": "5.1", "severity": "high",
        "in_force_from": datetime(2018, 5, 25, 10, 0), "title": "t", "applies_to": ["AC-x"],
    }  # fmt: skip
    with pytest.raises(ValueError, match="in_force_from"):
        parse_obligation(document)


def test_an_in_force_date_is_compared_as_a_date() -> None:
    stored = Literal(datetime(2030, 1, 1), datatype=XSD.date)
    assert in_force(date(2020, 1, 1), stored, None) is False


def test_an_unreadable_in_force_date_is_an_error_not_a_rule_for_ever() -> None:
    with pytest.raises(ValueError, match="date"):
        in_force(date(2020, 1, 1), Literal("2030-13-01", datatype=XSD.date), None)


def test_the_library_directory_exists() -> None:
    assert Path(LIBRARY_DIR).is_dir()
