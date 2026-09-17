"""ADR-0008 · synthetic subjects: marked, deterministic and never mistaken for a real person."""

import pytest

from argos_challenges.synthetic import (
    EMAIL_DOMAIN,
    IBAN_ENTITY,
    NAME_PREFIX,
    SYNTHETIC_DNI_RANGE,
    client_package,
    generate_subjects,
    is_synthetic,
)
from argos_connector.validators import is_valid_dni, is_valid_iban_es

SEED = "campaign-2026-09-17"


def test_the_same_seed_gives_the_same_subjects() -> None:
    assert generate_subjects(SEED, 3) == generate_subjects(SEED, 3)
    assert generate_subjects("another", 3) != generate_subjects(SEED, 3)


def test_every_marker_is_valid_but_unmistakably_synthetic() -> None:
    low, high = SYNTHETIC_DNI_RANGE
    for subject in generate_subjects(SEED, 5):
        assert is_valid_dni(subject.national_id)
        assert low <= int(subject.national_id[:-1]) <= high
        assert is_valid_iban_es(subject.iban)
        assert subject.iban[4:8] == IBAN_ENTITY
        assert subject.email.endswith(f"@{EMAIL_DOMAIN}")
        assert subject.full_name.startswith(NAME_PREFIX)


def test_the_synthetic_range_does_not_touch_the_inventory_ground_truth() -> None:
    low, _ = SYNTHETIC_DNI_RANGE
    assert low > 99991000  # the simulated sources use 99990001-99991000 (F03-00)


def test_a_synthetic_value_is_recognised_and_a_real_looking_one_is_not() -> None:
    subject = generate_subjects(SEED, 1)[0]
    assert is_synthetic(subject.national_id)
    assert is_synthetic(subject.email)
    assert is_synthetic(subject.iban)
    assert is_synthetic(subject.full_name)
    assert not is_synthetic("12345678Z")
    assert not is_synthetic("paciente@hospital.example.org")
    assert not is_synthetic("ES9121000418450200051332")


def test_subjects_are_numbered_and_carry_their_hashes() -> None:
    subjects = generate_subjects(SEED, 2)
    assert [s.index for s in subjects] == [0, 1]
    for subject in subjects:
        assert set(subject.value_hashes) == {"national_id", "iban", "email", "full_name"}
        assert all(len(digest) == 64 for digest in subject.value_hashes.values())


def test_the_client_package_carries_the_values_and_how_to_undo_it() -> None:
    subject = generate_subjects(SEED, 1)[0]
    injections = [
        {
            "id": "i-1",
            "system_id": "s-1",
            "point": "clinic.patients",
            "method": "SQL del cliente",
            "revert": "DELETE FROM clinic.patients WHERE national_id = :national_id",
        }
    ]
    package = client_package(subject, injections)
    assert package["values"]["national_id"] == subject.national_id
    assert package["injections"][0]["revert"].startswith("DELETE")
    assert "value_hashes" in package and package["subject_id"] == subject.id


@pytest.mark.parametrize("count", [0, -1])
def test_a_count_below_one_is_rejected(count: int) -> None:
    with pytest.raises(ValueError, match="count"):
        generate_subjects(SEED, count)
