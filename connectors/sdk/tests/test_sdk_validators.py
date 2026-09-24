"""ARG-024 · deterministic validators of Spanish identifiers (synthetic vectors only)."""

import pytest

from argos_connector.validators import (
    VALIDATORS,
    acceptance_rates,
    is_valid_dni,
    is_valid_iban_es,
    is_valid_nie,
    is_valid_nuss,
    mrn_validator,
    resolve_validators,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("00000000T", True),
        ("99990001P", True),
        (" 99991000h ", True),
        ("99990001A", False),
        ("1234567Z", False),
        ("", False),
        (99990001, False),
    ],
)
def test_dni(value: object, expected: bool) -> None:
    assert is_valid_dni(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("X0000000T", True), ("Y0000000Z", True), ("Z0000000M", True), ("X0000000A", False)],
)
def test_nie(value: str, expected: bool) -> None:
    assert is_valid_nie(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("281234567840", True),  # concatenation; number >= 10 000 000
        ("280123456785", True),  # concatenation
        ("280123456742", True),  # number < 10 000 000: number + province * 10 000 000
        ("28/01234567/42", True),
        ("080000099995", True),
        ("080000099955", True),
        ("280123456700", False),
        ("28123456784", False),
    ],
)
def test_nuss_accepts_both_published_computations(value: str, expected: bool) -> None:
    assert is_valid_nuss(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ES5799990001000000000001", True),
        ("es57 9999 0001 0000 0000 0001", True),
        ("ES5899990001000000000001", False),
        ("FR7630006000011234567890189", False),
    ],
)
def test_spanish_iban(value: str, expected: bool) -> None:
    assert is_valid_iban_es(value) is expected


def test_medical_record_numbers_follow_the_configured_pattern() -> None:
    check = mrn_validator(r"HC-\d{6}")
    assert check("HC-000001") and not check("HC-1") and not check(None)
    with pytest.raises(ValueError, match="pattern"):
        mrn_validator("")
    with pytest.raises(ValueError, match="pattern"):
        mrn_validator("a" * 201)


def test_resolve_validators() -> None:
    resolved = resolve_validators(["dni", "mrn"], mrn_pattern=r"HC-\d{6}")
    assert set(resolved) == {"dni", "mrn"} and resolved["dni"] is VALIDATORS["dni"]
    with pytest.raises(ValueError, match="unknown validator"):
        resolve_validators(["passport"])
    with pytest.raises(ValueError, match="configured pattern"):
        resolve_validators(["mrn"])
    assert resolve_validators([]) == {}


def test_acceptance_rates_ignore_nulls() -> None:
    values = ["99990001P", "99990001A", None, "99991000H"]
    rates, seen = acceptance_rates(values, {"dni": is_valid_dni, "nie": is_valid_nie})
    assert (rates, seen) == ({"dni": 0.6667, "nie": 0.0}, 3)
    assert acceptance_rates([None], {"dni": is_valid_dni}) == ({"dni": 0.0}, 0)


def test_scrub_identifiers_replaces_only_what_validates() -> None:
    from argos_connector.validators import scrub_identifiers

    table = [{"marker": "DNI", "validator": "dni", "pattern": r"(?<!\d)\d{8}[A-Za-z]"}]
    clean, substitutions = scrub_identifiers("00000000T y 00000000T, no 00000000A", table)
    assert clean == "[DNI-1] y [DNI-1], no 00000000A"
    assert substitutions == 2
