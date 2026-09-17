"""ARG-050 · the library that ships with the product, as the phase test will use it.

This is not a test of the DSL (that is `test_challenge_dsl.py`) but of the content: the challenges
the demonstration needs exist, pass the product rules, cover more than one norm and declare a
minimisation that the probe they use can actually honour.
"""

from pathlib import Path

import pytest
import yaml

from argos_challenges.dsl import ChallengeSpec, LintContext, lint_challenge
from argos_challenges.library.catalog import load_library
from argos_challenges.probes import CAPTURE_KEYS, INVENTORY_QUERIES
from argos_ontology.traceability import load_challenge_catalog

GROUND_TRUTH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "campaign_ground_truth.yaml"
)
MINIMUM = 15
# Ids the populations cite and the demonstration cannot answer: no breach register, no training
# data declaration and a model serving outside the simulated sources (F05-18).
WITHOUT_EVIDENCE = frozenset(
    {
        "brc-breach-register",
        "coh-ai-training-data-governance",
        "sec-ai-event-logging",
        "sec-ai-log-retention",
    }
)


@pytest.fixture(scope="module")
def library() -> dict[str, ChallengeSpec]:
    return load_library()


@pytest.fixture(scope="module")
def context() -> LintContext:
    return LintContext.from_library()


def _ground_truth_ids() -> set[str]:
    document = yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8"))
    ids = set(document["challenges"])
    ids.update(entry["challenge"] for entry in document.get("unverifiable", []))
    return ids


def test_every_shipped_challenge_passes_the_product_rules(
    library: dict[str, ChallengeSpec], context: LintContext
) -> None:
    breaches = [message for spec in library.values() for message in lint_challenge(spec, context)]
    assert breaches == []


def test_the_library_ships_at_least_fifteen_challenges_of_two_norms(
    library: dict[str, ChallengeSpec],
) -> None:
    assert len(library) >= MINIMUM
    norms = {spec.obligation.split("-")[1] for spec in library.values()}
    assert {"RGPD", "AIACT"} <= norms


@pytest.mark.parametrize("challenge_id", sorted(_ground_truth_ids()))
def test_every_challenge_of_the_campaign_ground_truth_is_written_or_reserved(
    challenge_id: str, library: dict[str, ChallengeSpec]
) -> None:
    """Reserved is honest: the demonstration has no evidence source for those four (see §9)."""
    assert challenge_id in library or challenge_id in load_challenge_catalog()


def test_the_challenges_without_an_evidence_source_stay_reserved(
    library: dict[str, ChallengeSpec],
) -> None:
    """Writing a challenge that can only ever answer `inconclusive` would be filler."""
    assert WITHOUT_EVIDENCE.isdisjoint(library)
    assert set(load_challenge_catalog()) >= WITHOUT_EVIDENCE


def test_every_declared_capture_can_be_honoured_by_its_probe(
    library: dict[str, ChallengeSpec],
) -> None:
    """A minimisation that lets nothing through would make the challenge unreadable."""
    for spec in library.values():
        assert spec.capture, spec.id
        assert all(name in CAPTURE_KEYS for name in spec.capture), spec.id


def test_every_internal_probe_asks_a_question_argos_answers(
    library: dict[str, ChallengeSpec],
) -> None:
    for spec in library.values():
        if spec.probe_kind == "inventory_query":
            assert spec.params.get("query") in INVENTORY_QUERIES, spec.id


def test_a_sql_variant_never_interpolates_a_value(library: dict[str, ChallengeSpec]) -> None:
    for spec in library.values():
        for connector, variant in spec.by_connector.items():
            statement = str(variant.get("statement") or "")
            assert "{" not in statement, f"{spec.id}/{connector}"
