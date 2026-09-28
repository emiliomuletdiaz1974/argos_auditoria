"""QA-28 · the challenge engine at its edges, without a database.

- QA-046: a count challenge that declares `muestreo` is evaluated as the census its probe is; it no
  longer breaks the campaign with a KeyError.
- QA-047: a threshold or an observation with decimals has a verdict and a hash.
- QA-053: the sample proposed for a strict `<` demonstrates it when no failure is found.
- QA-054: with sampling, `>=` and `>` cannot be decided on an upper bound: inconclusive.
- QA-056: the library is found wherever the repository lives, even under a folder `archive`.
"""

import shutil
from pathlib import Path

from argos_challenges.dsl import library_challenges
from argos_challenges.evaluator import evaluate

UNIT = {"unit_id": "u", "challenge_id": "c", "challenge_version": "1", "node_key": "n"}


def _unit(threshold: dict[str, object], sampling: dict[str, object] | None = None) -> dict:  # type: ignore[type-arg]
    return {**UNIT, "criterion": {"threshold": threshold}, "sampling": sampling}


def test_a_count_with_declared_sampling_is_decided_as_the_census_it_is() -> None:
    unit = _unit(
        {"field": "count", "operator": "<=", "value": 0}, {"confidence": 0.95, "margin": 0.05}
    )
    verdict = evaluate(unit, {"ok": True, "data": {"count": 0}})
    assert verdict.result == "compliant"
    assert verdict.detail["sampling"] == {"mode": "census"}


def test_decimals_have_a_verdict_and_a_hash() -> None:
    ratio = evaluate(_unit({"field": "ratio", "operator": "<=", "value": 0.05}),
                     {"ok": True, "data": {"ratio": 0.01}})  # fmt: skip
    assert ratio.result == "compliant" and len(ratio.hash) == 64
    counted = evaluate(_unit({"field": "count", "operator": "<=", "value": 3}),
                       {"ok": True, "data": {"count": 1.0}})  # fmt: skip
    assert counted.result == "compliant" and len(counted.hash) == 64
    assert ratio.hash == evaluate(_unit({"field": "ratio", "operator": "<=", "value": 0.05}),
                                  {"ok": True, "data": {"ratio": 0.01}}).hash  # fmt: skip


def test_the_proposed_sample_for_a_strict_threshold_demonstrates_it() -> None:
    first = evaluate(
        _unit({"field": "count", "operator": "<", "value": 1000},
              {"population": 1_000_000, "sample": 400, "confidence": 0.95}),
        {"ok": True, "data": {"count": 0}},
    )  # fmt: skip
    assert first.result == "not_demonstrated"
    required = first.detail["sampling"]["required_sample"]
    again = evaluate(
        _unit({"field": "count", "operator": "<", "value": 1000},
              {"population": 1_000_000, "sample": required, "confidence": 0.95}),
        {"ok": True, "data": {"count": 0}},
    )  # fmt: skip
    assert again.result == "compliant"


def test_a_lower_bound_cannot_be_decided_on_a_sample() -> None:
    verdict = evaluate(
        _unit({"field": "count", "operator": ">=", "value": 10},
              {"population": 100_000, "sample": 400, "confidence": 0.95}),
        {"ok": True, "data": {"count": 3}},
    )  # fmt: skip
    assert verdict.result == "inconclusive"


def test_the_library_is_found_under_folders_called_schema_or_archive(tmp_path: Path) -> None:
    from argos_challenges.library.catalog import load_library

    library = Path(__file__).resolve().parents[3] / "library" / "challenges"
    copy = tmp_path / "schema" / "archive" / "challenges"
    shutil.copytree(library, copy)
    assert len(library_challenges(copy)) == len(library_challenges(library))
    assert set(load_library(copy)) == set(load_library(library))
