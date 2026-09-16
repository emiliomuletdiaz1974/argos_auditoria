"""ARG-028 · pure pieces of AI discovery: signals, aggregation and weak-signal matchers."""

import pytest

from argos_inventory.ai_discovery.detect import (
    Signal,
    aggregate_confidence,
    is_ai_route,
    is_score_column,
)


def test_aggregate_confidence_combines_independent_signals() -> None:
    assert aggregate_confidence([0.4, 0.3]) == 0.58
    assert aggregate_confidence([0.5]) == 0.5
    assert aggregate_confidence([]) == 0.0
    assert aggregate_confidence([0.9, 0.9, 0.9, 0.9]) <= 1.0


def test_signals_round_trip_through_their_text_form() -> None:
    signal = Signal("score_column", 0.3, "readmission_risk")
    assert signal.encode() == "score_column|0.3|readmission_risk"
    assert Signal.decode(signal.encode()) == signal
    assert Signal.decode("route|0.5|/v1/chat|x").detail == "/v1/chat|x"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/predict", True),
        ("/models/{id}/inference", True),
        ("/v1/chat/completions", True),
        ("/api/Embeddings", True),
        ("/realms/{realm}", False),
        ("/scores-history", False),
    ],
)
def test_ai_routes(path: str, expected: bool) -> None:
    assert is_ai_route(path) is expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("risk_score", True),
        ("churnPrediction", True),
        ("default_probability", True),
        ("scoreboard", False),
        ("predicate", False),
        ("department", False),
    ],
)
def test_score_columns(name: str, expected: bool) -> None:
    assert is_score_column(name) is expected
