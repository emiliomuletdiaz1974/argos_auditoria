"""ARG-045 · sampling and Wilson vectors calculated by hand, fixed before the implementation."""

import importlib
from pathlib import Path
from typing import Any

import pytest
import yaml

VECTORS_FILE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "sampling_vectors.yaml"
DOCUMENT = yaml.safe_load(VECTORS_FILE.read_text(encoding="utf-8"))
PENDING = pytest.mark.xfail(
    raises=ModuleNotFoundError, strict=True, reason="argos_challenges.sampling arrives in F05-08"
)


def _function(name: str) -> Any:
    return getattr(importlib.import_module("argos_challenges.sampling"), name)


def _label(vector: dict[str, Any]) -> str:
    args = ",".join(f"{k}={v}" for k, v in vector["args"].items())
    return f"{vector['function']}({args})"


def test_the_vectors_file_documents_every_vector() -> None:
    assert DOCUMENT["version"] == 1
    assert len(DOCUMENT["vectors"]) >= 10
    for vector in DOCUMENT["vectors"]:
        assert vector["note"].strip(), _label(vector)


@PENDING
@pytest.mark.parametrize("vector", DOCUMENT["vectors"], ids=_label)
def test_hand_calculated_vector(vector: dict[str, Any]) -> None:
    result = _function(vector["function"])(**vector["args"])
    if isinstance(vector["expected"], int):
        assert result == vector["expected"]
    else:
        assert result == pytest.approx(vector["expected"], abs=DOCUMENT["tolerance"])


@PENDING
@pytest.mark.parametrize("vector", DOCUMENT["invalid"], ids=_label)
def test_invalid_arguments_are_rejected(vector: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _function(vector["function"])(**vector["args"])
