"""F05-01 · the campaign ground truth agrees with the applicability truth, library and catalog."""

from pathlib import Path

import pytest
from rdflib import URIRef

from argos_ontology.traceability import library_graph, load_challenge_catalog
from argos_ontology.vocabulary import ARGOS, NORMS
from fixtures.applicability_ground_truth import load_applicability_truth
from fixtures.campaign_ground_truth import CAMPAIGN_TRUTH_FILE, load_campaign_truth

TRUTH = load_campaign_truth()
APPLICABILITY = load_applicability_truth()
LIBRARY = library_graph()


def _planned_pairs() -> set[tuple[str, str]]:
    return {
        (row.challenge_id, node.split(" ", 1)[0])
        for row in APPLICABILITY.expected_plan(TRUTH.campaign_date)
        for node in row.nodes
    }


def test_every_planned_challenge_and_system_has_exactly_one_expectation() -> None:
    expected = {(v.challenge_id, v.system) for v in TRUTH.verdicts}
    expected |= {(u.challenge_id, u.system) for u in TRUTH.unverifiable}
    assert expected == _planned_pairs()


def test_challenges_come_from_the_catalog_and_verify_their_obligation() -> None:
    catalog = load_challenge_catalog()
    for challenge_id, obligation in TRUTH.obligations.items():
        assert challenge_id in catalog
        verifiers = {
            str(LIBRARY.value(ch, ARGOS.challengeId))
            for ch in LIBRARY.objects(URIRef(NORMS[obligation]), ARGOS.verifiedBy)
        }
        assert challenge_id in verifiers, (challenge_id, obligation)


def test_findings_are_exactly_the_non_compliant_expectations() -> None:
    assert {(f.challenge_id, f.system) for f in TRUTH.findings} == {
        (v.challenge_id, v.system) for v in TRUTH.verdicts if v.result == "non_compliant"
    }
    for finding in TRUTH.findings:
        assert LIBRARY.value(URIRef(NORMS[finding.obligation]), ARGOS.severity) is not None


def test_the_phase_test_has_at_least_15_decided_challenges_of_two_norms() -> None:
    decided = {v.challenge_id for v in TRUTH.verdicts if v.result in ("compliant", "non_compliant")}
    norms = {TRUTH.obligations[c].split("-")[1] for c in decided}
    assert len(decided) >= 15
    assert {"RGPD", "AIACT"} <= norms


def test_planted_findings_are_expected() -> None:
    planted = {
        ("acc-special-category-profiles", "dev-source-mariadb"),
        ("dsr-erasure-effective", "dev-source-mariadb"),
        ("coh-treatment-legal-basis", "dev-source-mariadb"),
        ("doc-ai-technical-documentation", "dev-source-postgres"),
    }
    assert planted <= {(f.challenge_id, f.system) for f in TRUTH.findings}


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "result: compliant\n      reason: log_statement",
            "result: maybe\n      reason: x",
            "unknown",
        ),
        ("dev-source-mariadb: non_compliant\n", "dev-source-mariadb: compliant\n", "aggregate"),
        ("reason: ssl = off", "reason: ''", "reason"),
    ],
)
def test_malformed_truth_is_rejected(tmp_path: Path, old: str, new: str, message: str) -> None:
    text = CAMPAIGN_TRUTH_FILE.read_text(encoding="utf-8")
    assert old in text
    bad = tmp_path / "bad.yaml"
    bad.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_campaign_truth(bad)
