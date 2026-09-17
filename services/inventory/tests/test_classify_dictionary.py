"""ARG-024 · name dictionary by whole tokens and validator hints (pure)."""

import pytest

from argos_inventory.classify.deterministic import ColumnRef, best_validation
from argos_inventory.classify.dictionary import (
    NAME_DICTIONARY,
    VALIDATOR_CATEGORY,
    match_column_in_table,
    match_column_name,
    name_tokens,
    validator_hints,
)
from argos_inventory.graph.model import CATEGORIES


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("dni_number", ("dni", "number")),
        ("fechaNacimiento", ("fecha", "nacimiento")),
        ("ICD10-code", ("icd10", "code")),
        ("  Full Name ", ("full", "name")),
    ],
)
def test_name_tokens(name: str, expected: tuple[str, ...]) -> None:
    assert name_tokens(name) == expected


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("national_id", "official_identifier"),
        ("dni_number", "official_identifier"),
        ("full_name", "personal_data"),
        ("birth_date", "personal_data"),
        ("patient_id", "personal_data"),
        ("patient_ref", "personal_data"),
        ("id_paciente", "personal_data"),
        ("trade_union", "special_category.other"),
        ("afiliacion_sindical", "special_category.other"),
        ("fingerprint_hash", "special_category.other"),
        ("sexual_orientation", "special_category.other"),
        ("fecha_nacimiento", "personal_data"),
        ("diagnosis_code", "special_category.health"),
        ("email", "contact_data"),
        ("iban", "financial_data"),
        ("home_address", "location_data"),
        ("api_key", "technical_credential"),
    ],
)
def test_dictionary_classifies_revealing_names(name: str, category: str) -> None:
    assert match_column_name(name) == category


@pytest.mark.parametrize(
    "name",
    [
        "department",
        "purpose",
        "amount_cents",
        "status",
        "translation",
        "platform",
        "unified_id",
        "id",
        "staff_id",
        "union_id",
        "joined_on",
        "risk_score",
        "created_at",
        "admin",
    ],
)
def test_dictionary_does_not_match_substrings(name: str) -> None:
    assert match_column_name(name) is None


@pytest.mark.parametrize(
    ("name", "table", "category"),
    [
        ("risk_score", "clinic.readmission_risk", "special_category.health"),
        ("probability", "icu.mortality_model", "special_category.health"),
        ("pred", "er.triaje_urgencias", "special_category.health"),
        ("risk_score", "bank.credit_risk", None),
        ("created_at", "clinic.readmission_risk", None),
        ("patient_id", "clinic.readmission_risk", "personal_data"),
    ],
)
def test_score_columns_of_clinical_inference_tables_are_health_data(
    name: str, table: str, category: str | None
) -> None:
    assert match_column_in_table(name, table) == category


def test_dictionary_uses_only_known_categories() -> None:
    assert set(NAME_DICTIONARY) <= set(CATEGORIES)
    assert set(VALIDATOR_CATEGORY.values()) <= set(CATEGORIES)


def test_validator_hints() -> None:
    assert validator_hints("dni_number") == ("dni",)
    assert validator_hints("iban") == ("iban_es",)
    assert validator_hints("num_seg_social") == ("nuss",)
    assert validator_hints("national_id") == ()
    assert validator_hints("nhc") == ()  # mrn only when the system configures a pattern
    assert validator_hints("nhc", frozenset({"mrn"})) == ("mrn",)


def test_best_validation_needs_the_acceptance_rate() -> None:
    column = ColumnRef("k", "dni_number", "clinic.patient_documents")
    accepted = ("official_identifier", "validator:dni", 1.0)
    assert best_validation(column, {"dni": 1.0}, ("dni",)) == accepted
    assert best_validation(column, {"dni": 0.89}, ("dni",)) is None
    assert best_validation(column, {}, ("dni",)) is None
    both = ColumnRef("k", "doc_dni_nie", "t.t")
    assert best_validation(both, {"dni": 0.95, "nie": 0.99}, ("dni", "nie")) == (
        "official_identifier",
        "validator:nie",
        0.99,
    )
