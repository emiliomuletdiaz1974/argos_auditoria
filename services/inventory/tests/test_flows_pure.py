"""ARG-027 · pure parts of flow detection: link hosts, Jaccard and structural blocking."""

import pytest

from argos_inventory.flows.detect import (
    STRUCTURAL_MAX_CONFIDENCE,
    jaccard,
    link_host,
    structural_candidates,
)


@pytest.mark.parametrize(
    ("options", "host"),
    [
        ("['host=source-mariadb', 'port=3306', 'dbname=billing']", "source-mariadb"),
        ("{host=erp.example.invalid,port=5432}", "erp.example.invalid"),
        ("sqlerp.example.invalid,1433", "sqlerp.example.invalid"),
        (r"sqlerp\INSTANCE", "sqlerp"),
        ("['dbname=billing']", None),
        (None, None),
    ],
)
def test_link_host(options: str | None, host: str | None) -> None:
    assert link_host(options) == host


def test_jaccard() -> None:
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b", "c", "d"}, {"a", "b", "c", "e"}) == 0.6
    assert jaccard(set(), set()) == 0.0


def _signature(*pairs: str) -> frozenset[str]:
    return frozenset(pairs)


def test_structural_candidates_need_shared_special_categories_and_other_systems() -> None:
    documents = _signature(
        "dni_number|official_identifier",
        "iban|financial_data",
        "diagnosis_code|special_category.health",
        "email|contact_data",
    )
    signatures = {
        ("s1", "clinic.patient_documents"): documents,
        ("s2", "billing.patient_mirror"): documents,
        ("s1", "clinic.copy_in_same_system"): documents,
        ("s3", "crm.contacts"): _signature(
            "dni_number|official_identifier",
            "iban|financial_data",
            "email|contact_data",
            "phone|contact_data",
        ),
        ("s4", "small.table"): _signature(
            "diagnosis_code|special_category.health", "email|contact_data"
        ),
    }
    candidates = structural_candidates(signatures)
    pairs = {(a[0], b[0]) for a, b, _ in candidates}
    assert pairs == {("s1", "s2")} or pairs == {("s1", "s2"), ("s2", "s1")}
    assert all(score == 1.0 for _, _, score in candidates)
    assert len(candidates) == 2  # patient_documents and copy_in_same_system each against s2
    assert STRUCTURAL_MAX_CONFIDENCE == 0.6
