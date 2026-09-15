"""Deterministic validators of Spanish identifiers, run inside connectors (ARG-024, P-09).

Pure and I/O-free. They travel to the connector so that sampled values are validated in memory and
only acceptance rates leave it (deviation note ARG-024-025).
"""

import re
from collections.abc import Callable, Iterable, Mapping

DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
MAX_PATTERN_LENGTH = 200
_NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}
_DNI = re.compile(r"(\d{8})([A-Z])")
_NIE = re.compile(r"([XYZ])(\d{7})([A-Z])")
_IBAN_ES = re.compile(r"ES\d{22}")

Validator = Callable[[object], bool]


def is_valid_dni(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = _DNI.fullmatch(value.strip().upper())
    if match is None:
        return False
    return DNI_LETTERS[int(match[1]) % 23] == match[2]


def is_valid_nie(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = _NIE.fullmatch(value.strip().upper())
    if not match:
        return False
    number = int(_NIE_PREFIX[match[1]] + match[2])
    return DNI_LETTERS[number % 23] == match[3]


def is_valid_nuss(value: object) -> bool:
    """Social Security number: province (2) + number (8) + control (2).

    Two computations are published and no official source was available when this was written
    (deviation note ARG-024-025): the plain 10-digit concatenation mod 97, and, for numbers below
    10 000 000, number + province * 10 000 000 mod 97. Either control is accepted.
    """
    if not isinstance(value, str):
        return False
    digits = re.sub(r"[\s/-]", "", value)
    if not re.fullmatch(r"\d{12}", digits):
        return False
    province, number, control = int(digits[:2]), int(digits[2:10]), int(digits[10:])
    candidates = {int(digits[:10]) % 97}
    if number < 10_000_000:
        candidates.add((number + province * 10_000_000) % 97)
    return control in candidates


def is_valid_iban_es(value: object) -> bool:
    if not isinstance(value, str):
        return False
    compact = re.sub(r"\s", "", value.upper())
    if not _IBAN_ES.fullmatch(compact):
        return False
    return int(compact[4:] + "1428" + compact[2:4]) % 97 == 1  # E=14, S=28


def mrn_validator(pattern: str) -> Validator:
    """Medical record numbers differ per hospital: the pattern comes from the system config."""
    if not pattern or len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError("invalid medical record number pattern")
    compiled = re.compile(pattern)

    def check(value: object) -> bool:
        return isinstance(value, str) and compiled.fullmatch(value.strip()) is not None

    return check


VALIDATORS: Mapping[str, Validator] = {
    "dni": is_valid_dni,
    "nie": is_valid_nie,
    "nuss": is_valid_nuss,
    "iban_es": is_valid_iban_es,
}


def resolve_validators(
    names: Iterable[str], mrn_pattern: str | None = None
) -> dict[str, Validator]:
    resolved: dict[str, Validator] = {}
    for name in names:
        if name == "mrn":
            if not mrn_pattern:
                raise ValueError("the mrn validator needs a configured pattern (mrn_pattern)")
            resolved[name] = mrn_validator(mrn_pattern)
        elif name in VALIDATORS:
            resolved[name] = VALIDATORS[name]
        else:
            raise ValueError(f"unknown validator: {name!r}")
    return resolved


def acceptance_rates(
    values: Iterable[object], validators: Mapping[str, Validator]
) -> tuple[dict[str, float], int]:
    present = [value for value in values if value is not None]
    if not present:
        return {name: 0.0 for name in validators}, 0
    rates = {
        name: round(sum(1 for value in present if check(value)) / len(present), 4)
        for name, check in validators.items()
    }
    return rates, len(present)
