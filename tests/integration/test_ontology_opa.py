"""ARG-036 · the dev OPA server loads the shipped policies and the synthetic client data."""

import os

import httpx
import pytest

from argos_ontology.opa import OpaError, evaluate

pytestmark = pytest.mark.integration

OPA = os.environ.get("ARGOS_TEST_OPA", "http://127.0.0.1:8181")


@pytest.fixture(scope="module", autouse=True)
def opa_is_up() -> None:
    try:
        httpx.get(f"{OPA}/health", timeout=2.0).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.fail(f"OPA is not running at {OPA} (make dev): {exc}")


def test_retention_verdict_uses_the_client_schedule() -> None:
    verdict = evaluate(
        "argos.retention",
        {
            "category": "special_category.health",
            "treatment": "HIS-episodes",
            "max_age_days": 6000,
            "out_of_term": 3,
            "documented_exceptions": 1,
        },
        OPA,
    )
    assert verdict == {"compliant": False, "applied_term_days": 5475, "rule": "argos.retention"}


def test_access_verdict_lists_the_unauthorized_identities() -> None:
    verdict = evaluate(
        "argos.access",
        {
            "target": "his.episodes",
            "category": "special_category.health",
            "identities": [
                {"name": "svc_bi", "profile": None},
                {"name": "dr.garcia", "profile": "physician"},
            ],
        },
        OPA,
    )
    assert verdict == {
        "compliant": False,
        "unauthorized": ["svc_bi"],
        "total": 2,
        "rule": "argos.access",
    }


def test_test_files_are_not_served() -> None:
    with pytest.raises(OpaError, match="verdict"):
        evaluate("argos.retention_test", {}, OPA)
