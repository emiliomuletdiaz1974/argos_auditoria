"""ARG-056 · the jurist only sees proposals that already compile (F06-09).

The model proposes the YAML, but the same `lint_challenge` the CI runs decides whether it is shown.
A proposal that fails gets one repair cycle with its errors; a proposal that writes is refused,
because a probe that writes is not a mistake to correct but a line the product does not cross.
"""

import asyncio
import hashlib
import json

import pytest
from argos_ai.backends.fake import FakeBackend
from argos_ai.gateway import Gateway
from argos_ai.generate.challenge_gen import PROMPT_FILE, ChallengeProposal, propose_challenge

from argos_challenges.dsl import LintContext
from argos_ontology.vocabulary import LIBRARY_DIR

CONTEXT = LintContext.from_library()
VALID = (LIBRARY_DIR / "challenges" / "sec" / "sec-encryption-in-transit.yaml").read_text(
    encoding="utf-8"
)
OBLIGATION = "OBL-RGPD-32-3"
TEXT = "Cifrado en tránsito hacia los sistemas con datos personales."


def _propose(replies: list[str]) -> tuple[ChallengeProposal, FakeBackend]:
    backend = FakeBackend.of([json.dumps({"yaml": reply}) for reply in replies])
    gateway = Gateway(
        backend, journal=lambda _: None, usage=lambda _: None, quotas={"challenge": 1_000_000}
    )
    proposal = asyncio.run(propose_challenge(OBLIGATION, TEXT, gateway, CONTEXT))
    return proposal, backend


def test_a_proposal_that_compiles_is_shown_as_valid() -> None:
    proposal, backend = _propose([VALID])
    assert proposal.valid is True
    assert proposal.warnings == []
    assert backend.calls == 1


def test_a_proposal_that_fails_the_lint_gets_one_repair_with_its_errors() -> None:
    broken = VALID.replace("OBL-RGPD-32-3", "OBL-RGPD-99-9")
    proposal, backend = _propose([broken, VALID])
    assert proposal.valid is True
    assert backend.calls == 2
    assert "OBL-RGPD-99-9" in backend.last_user, "the repair must carry the lint errors back"


def test_a_proposal_that_still_fails_after_the_repair_is_not_valid() -> None:
    broken = VALID.replace("OBL-RGPD-32-3", "OBL-RGPD-99-9")
    proposal, backend = _propose([broken, broken])
    assert proposal.valid is False
    assert any("OBL-RGPD-99-9" in warning for warning in proposal.warnings)
    assert backend.calls == 2, "one repair, not an endless retry"


def test_a_proposal_that_is_not_even_yaml_is_repaired_too() -> None:
    proposal, _ = _propose(["esto: no: es: yaml: válido: [", VALID])
    assert proposal.valid is True


def test_a_probe_that_writes_is_refused_and_not_repaired() -> None:
    """Repairing it would teach the model how to slip a write past the lint."""
    writes = VALID.replace(
        "SELECT setting FROM pg_settings WHERE name = 'ssl'", "DELETE FROM pg_settings"
    )
    proposal, backend = _propose([writes, VALID])
    assert proposal.valid is False
    assert backend.calls == 1
    assert any("escritura" in warning for warning in proposal.warnings)


def test_the_prompt_carries_the_schema_the_probes_and_two_complete_examples() -> None:
    _, backend = _propose([VALID])
    assert '"$schema"' in backend.last_system
    assert "check_config" in backend.last_system and "inventory_query" in backend.last_system
    assert backend.last_system.count("id: ") >= 2


def test_the_prompt_is_versioned_and_its_hash_travels_with_the_proposal() -> None:
    proposal, _ = _propose([VALID])
    assert proposal.prompt_sha256 == hashlib.sha256(PROMPT_FILE.read_bytes()).hexdigest()


def test_the_obligation_the_jurist_pasted_reaches_the_model() -> None:
    _, backend = _propose([VALID])
    assert OBLIGATION in backend.last_user and TEXT in backend.last_user


@pytest.mark.parametrize(
    "statement", ["UPDATE t SET a = 1", "DROP TABLE t", "INSERT INTO t VALUES (1)"]
)
def test_every_kind_of_write_is_refused(statement: str) -> None:
    writes = VALID.replace("SELECT setting FROM pg_settings WHERE name = 'ssl'", statement)
    proposal, _ = _propose([writes])
    assert proposal.valid is False
