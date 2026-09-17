"""Audit sampling: size, Wilson upper bound and the plan of a unit (ARG-045).

A pure module. On large populations a census is not viable, and honesty asks for two things: the
sample size for the declared confidence, and a verdict decided on the **upper bound** of the
non-compliance proportion, never on the point estimate. ARGOS does not absolve out of the optimism
of a sample.

Only IEEE operations that are correctly rounded are used (`+ - * /` and `sqrt`), so the
result is the same on every platform; the determinism suite of the verdict depends on it.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Two-sided z for each confidence admitted by the DSL.
Z: Mapping[float, float] = {0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}
POPULATION_THRESHOLD = 5_000  # below this, a census is cheaper than explaining a sample
DEFAULT_CONFIDENCE = 0.95
DEFAULT_MARGIN = 0.05


@dataclass(frozen=True, slots=True)
class SamplingPlan:
    mode: str  # "census" or "sample"
    population: int
    sample: int
    confidence: float
    margin: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "population": self.population,
            "sample": self.sample,
            "confidence": f"{self.confidence:.2f}",
            "margin": f"{self.margin:.3f}",
        }


def _z(confidence: float) -> float:
    if confidence not in Z:
        raise ValueError(f"unsupported confidence: {confidence!r}; use one of {sorted(Z)}")
    return Z[confidence]


def sample_size(
    population: int,
    confidence: float = DEFAULT_CONFIDENCE,
    margin: float = DEFAULT_MARGIN,
    proportion: float = 0.5,
) -> int:
    """Sample for a proportion with the finite population correction, the audit standard."""
    z = _z(confidence)
    if population < 1:
        raise ValueError("population must be at least 1")
    if not 0 < margin <= 0.5:
        raise ValueError("margin must be in (0, 0.5]")
    base = (z * z * proportion * (1 - proportion)) / (margin * margin)
    corrected = base / (1 + (base - 1) / population)
    return min(population, math.ceil(corrected))


def wilson_upper(failures: int, sample: int, confidence: float = DEFAULT_CONFIDENCE) -> float:
    """Upper bound of the Wilson interval for `failures` in `sample`. Without a sample, 1.0."""
    z = _z(confidence)
    if failures < 0 or sample < 0:
        raise ValueError("failures and sample must not be negative")
    if failures > sample:
        raise ValueError("there cannot be more failures than sampled items")
    if sample == 0:
        return 1.0
    observed = failures / sample
    denominator = 1 + z * z / sample
    centre = observed + z * z / (2 * sample)
    spread = z * math.sqrt(observed * (1 - observed) / sample + z * z / (4 * sample * sample))
    return min(1.0, (centre + spread) / denominator)


def required_sample_size(
    failures: int, target: float, confidence: float = DEFAULT_CONFIDENCE
) -> int:
    """Smallest sample whose upper bound stays below `target`, with `failures` observed.

    With no failures the bound is `z^2 / (n + z^2)`, so the answer is exact; with failures it is
    searched upwards, because the bound is not monotone in closed form.
    """
    z = _z(confidence)
    if not 0 < target < 1:
        raise ValueError("target must be in (0, 1)")
    if failures == 0:
        return int(z * z * (1 / target - 1)) + 1
    size = max(failures, 1)
    while wilson_upper(failures, size, confidence) >= target:
        size += 1
    return size


def plan_sampling(unit: Mapping[str, Any], population: int) -> tuple[dict[str, Any], SamplingPlan]:
    """Decide census or sample for a unit.

    Returns a **new** unit: the one received never changes.
    """
    settings = unit.get("sampling") or {}
    confidence = float(settings.get("confidence", DEFAULT_CONFIDENCE))
    margin = float(settings.get("margin", DEFAULT_MARGIN))
    if population <= POPULATION_THRESHOLD:
        plan = SamplingPlan("census", population, population, confidence, margin)
        return {**dict(unit), "sampling": None}, plan
    size = sample_size(population, confidence, margin)
    plan = SamplingPlan("sample", population, size, confidence, margin)
    planned = {
        **dict(unit),
        "sampling": {
            "population": population,
            "sample": size,
            "confidence": f"{confidence:.2f}",
        },
    }
    return planned, plan
