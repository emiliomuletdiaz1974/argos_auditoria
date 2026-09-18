"""ARG-055 · the semantic classifier is the model ARG-025 was waiting for (F06-08).

It fills the `ClassificationModel` interface of Phase 03 without changing it: the inventory keeps
calling `propose(columns)` and keeps its triage. What changes is that the confidence it receives
has been calibrated against the DPO's own decisions first.
"""

import hashlib
import json

from argos_ai.backends.fake import FakeBackend
from argos_ai.classify.calibration import UNTRUSTED_CEILING, Calibrator, Decision
from argos_ai.classify.service import PROMPT_FILE, SemanticClassifier
from argos_ai.gateway import Gateway

from argos_inventory.classify.assisted import ColumnContext, triage

COLUMNS = [
    ColumnContext("k1", "amount_cents", "bigint", "billing.invoices", ("id", "issued_at")),
    ColumnContext("k2", "department", "text", "clinic.appointments", ("id", "starts_at")),
]


def _classifier(
    reply: dict[str, object], calibrator: Calibrator | None = None
) -> tuple[SemanticClassifier, FakeBackend]:
    backend = FakeBackend.of([json.dumps(reply)])
    gateway = Gateway(
        backend, journal=lambda _: None, usage=lambda _: None, quotas={"inventory": 1_000_000}
    )
    return SemanticClassifier(gateway, calibrator or Calibrator({})), backend


def test_it_answers_with_the_proposals_the_inventory_expects() -> None:
    classifier, _ = _classifier(
        {"items": [{"key": "k1", "category": "financial_data", "confidence": 0.6, "reason": "x"}]}
    )
    [proposal] = classifier.propose(COLUMNS)
    assert (proposal.key, proposal.category) == ("k1", "financial_data")


def test_the_confidence_the_triage_sees_is_the_calibrated_one() -> None:
    """The model says 0.95; its record in this category is one hit in two."""
    decisions = [
        Decision(
            "financial_data", 0.95, index % 2 == 0, __import__("datetime").datetime(2026, 9, 1)
        )
        for index in range(60)
    ]
    classifier, _ = _classifier(
        {"items": [{"key": "k1", "category": "financial_data", "confidence": 0.95, "reason": "x"}]},
        Calibrator.fit(decisions),
    )
    [proposal] = classifier.propose(COLUMNS)
    assert proposal.confidence == 0.5
    assert triage([proposal], frozenset({"k1"})).accepted == ()


def test_without_calibration_the_model_can_only_queue_for_review() -> None:
    classifier, _ = _classifier(
        {"items": [{"key": "k1", "category": "financial_data", "confidence": 0.99, "reason": "x"}]}
    )
    [proposal] = classifier.propose(COLUMNS)
    assert proposal.confidence == UNTRUSTED_CEILING
    result = triage([proposal], frozenset({"k1"}))
    assert result.accepted == () and len(result.review) == 1


def test_only_metadata_reaches_the_model_never_values() -> None:
    classifier, backend = _classifier({"items": []})
    classifier.propose(COLUMNS)
    assert "amount_cents" in backend.last_user and "billing.invoices" in backend.last_user
    assert "issued_at" in backend.last_user  # siblings travel, they are names too


def test_an_empty_batch_does_not_call_the_model() -> None:
    classifier, backend = _classifier({"items": []})
    assert classifier.propose([]) == []
    assert backend.calls == 0


def test_the_prompt_is_versioned_in_a_file_and_its_hash_travels() -> None:
    classifier, _ = _classifier({"items": []})
    expected = hashlib.sha256(PROMPT_FILE.read_bytes()).hexdigest()
    assert classifier.prompt_sha256 == expected


def test_the_declared_confidence_is_recorded_not_the_calibrated_one() -> None:
    """The next curve is fitted on what the model said. Fitting it on what the curve already
    corrected would feed the calibration its own output."""
    recorded: list[dict[str, object]] = []
    backend = FakeBackend.of(
        [json.dumps({"items": [{"key": "k1", "category": "financial_data", "confidence": 0.95}]})]
    )
    gateway = Gateway(
        backend, journal=lambda _: None, usage=lambda _: None, quotas={"inventory": 1_000_000}
    )
    classifier = SemanticClassifier(gateway, Calibrator({}), record=recorded.extend)
    [proposal] = classifier.propose(COLUMNS)
    assert proposal.confidence == UNTRUSTED_CEILING
    assert recorded == [
        {
            "node_key": "k1",
            "category": "financial_data",
            "declared": 0.95,
            "calibrated": UNTRUSTED_CEILING,
            "prompt_sha256": classifier.prompt_sha256,
        }
    ]
