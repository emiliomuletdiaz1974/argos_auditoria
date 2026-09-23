"""SEC-011 · OPA runs exactly the Rego of the signed bundle in force (F09-25)."""

import os
from datetime import date

import pytest

from argos_common.errors import IntegrityError
from argos_common.release import VaultTransitSigner
from argos_ontology.bundle import publish_library, verify_running_policies
from argos_ontology.opa import loaded_policies
from argos_ontology.vocabulary import LIBRARY_DIR

pytestmark = pytest.mark.integration

OPA = os.environ.get("ARGOS_TEST_OPA", "http://127.0.0.1:8181")
TOKEN = os.environ.get("ARGOS_OPA_TOKEN", "dev-only-opa-host")
VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")


def test_the_policies_opa_runs_are_the_signed_ones(migrated_db: str) -> None:
    signer = VaultTransitSigner(VAULT, "root", key="argos-content")
    publish_library(migrated_db, LIBRARY_DIR, "1.0.0", date(2026, 1, 1), signer)
    running = loaded_policies(OPA, token=TOKEN)
    assert any(module.endswith("retention.rego") for module in running)
    verify_running_policies(migrated_db, "1.0.0", running)

    softened = {
        module: raw + "\n# softened\n" if module.endswith("retention.rego") else raw
        for module, raw in running.items()
    }
    with pytest.raises(IntegrityError, match="retention.rego"):
        verify_running_policies(migrated_db, "1.0.0", softened)


def test_without_a_token_the_policies_are_not_readable() -> None:
    from argos_ontology.opa import OpaError

    with pytest.raises(OpaError, match="401|403"):
        loaded_policies(OPA)
