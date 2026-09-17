"""Column-name dictionary by whole tokens, and validator hints (ARG-024, note ARG-024-025).

Entries are token sequences (Spanish and English) matched as contiguous runs of the tokenised
column name, never as substrings: "lat" must not match "translation".
"""

import re
from collections.abc import Mapping

NAME_DICTIONARY: Mapping[str, tuple[tuple[str, ...], ...]] = {
    "official_identifier": (
        ("dni",),
        ("nif",),
        ("nie",),
        ("nuss",),
        ("ssn",),
        ("passport",),
        ("pasaporte",),
        ("national", "id"),
        ("documento", "identidad"),
        ("num", "seg", "social"),
    ),
    "special_category.health": (
        ("diagnosis",),
        ("diagnostico",),
        ("icd10",),
        ("cie10",),
        ("nhc",),
        ("mrn",),
        ("historia", "clinica"),
        ("medical", "record"),
        ("pathology",),
        ("patologia",),
        ("allergy",),
        ("alergia",),
    ),
    "personal_data": (
        ("full", "name"),
        ("first", "name"),
        ("last", "name"),
        ("surname",),
        ("nombre",),
        ("apellido",),
        ("apellidos",),
        ("birth", "date"),
        ("date", "of", "birth"),
        ("dob",),
        ("fecha", "nacimiento"),
        ("nacimiento",),
        # A pseudonymous reference to a patient still identifies a person (GDPR recital 26).
        ("patient", "id"),
        ("patient", "ref"),
        ("paciente", "id"),
        ("id", "paciente"),
    ),
    "contact_data": (
        ("email",),
        ("correo",),
        ("phone",),
        ("telefono",),
        ("movil",),
        ("mobile",),
    ),
    "financial_data": (
        ("iban",),
        ("cuenta", "bancaria"),
        ("bank", "account"),
        ("card", "number"),
        ("tarjeta",),
    ),
    "location_data": (
        ("address",),
        ("direccion",),
        ("domicilio",),
        ("latitude",),
        ("longitude",),
        ("gps",),
        ("postal", "code"),
        ("codigo", "postal"),
    ),
    "technical_credential": (
        ("password",),
        ("contrasena",),
        ("api", "key"),
        ("secret",),
        ("token",),
    ),
}
VALIDATOR_HINTS: Mapping[str, tuple[tuple[str, ...], ...]] = {
    "dni": (("dni",), ("nif",)),
    "nie": (("nie",),),
    "nuss": (("nuss",), ("ssn",), ("num", "seg", "social")),
    "iban_es": (("iban",),),
    "mrn": (("nhc",), ("mrn",), ("historia", "clinica"), ("medical", "record")),
}
VALIDATOR_CATEGORY: Mapping[str, str] = {
    "dni": "official_identifier",
    "nie": "official_identifier",
    "nuss": "official_identifier",
    "iban_es": "financial_data",
    "mrn": "special_category.health",
}
DEFAULT_VALIDATORS = frozenset({"dni", "nie", "nuss", "iban_es"})
# Score-like column names, shared with the AI discovery (ARG-028).
SCORE_TOKENS = frozenset({"score", "pred", "prediction", "probability", "propensity", "propension"})
# Tables whose scores are inferences about a patient's health (GDPR art. 4.15): the score alone is
# not health data (a credit risk score is not), the table gives the context.
CLINICAL_INFERENCE_TABLES: tuple[tuple[str, ...], ...] = (
    ("readmission",),
    ("reingreso",),
    ("mortality",),
    ("mortalidad",),
    ("sepsis",),
    ("triage",),
    ("triaje",),
)
TABLE_CONTEXT_METHOD = "dict:table"
_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_SEPARATORS = re.compile(r"[^a-z0-9]+")


def name_tokens(name: str) -> tuple[str, ...]:
    spaced = _CAMEL.sub(r"\1_\2", name.strip())
    return tuple(token for token in _SEPARATORS.split(spaced.lower()) if token)


def _contains(tokens: tuple[str, ...], sequence: tuple[str, ...]) -> bool:
    size = len(sequence)
    return any(tokens[i : i + size] == sequence for i in range(len(tokens) - size + 1))


def match_column_name(name: str) -> str | None:
    tokens = name_tokens(name)
    for category, sequences in NAME_DICTIONARY.items():
        if any(_contains(tokens, sequence) for sequence in sequences):
            return category
    return None


def match_column_in_table(name: str, table: str) -> str | None:
    """The dictionary category of a column, or health data for a score of a clinical inference."""
    category = match_column_name(name)
    if category is not None:
        return category
    table_tokens = name_tokens(table.rsplit(".", 1)[-1])
    if any(token in SCORE_TOKENS for token in name_tokens(name)) and any(
        _contains(table_tokens, sequence) for sequence in CLINICAL_INFERENCE_TABLES
    ):
        return "special_category.health"
    return None


def validator_hints(name: str, available: frozenset[str] = DEFAULT_VALIDATORS) -> tuple[str, ...]:
    tokens = name_tokens(name)
    return tuple(
        validator
        for validator, sequences in VALIDATOR_HINTS.items()
        if validator in available and any(_contains(tokens, s) for s in sequences)
    )
