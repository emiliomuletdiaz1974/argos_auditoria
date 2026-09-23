"""The deterministic evaluator: the only place where a verdict is born (ARG-046).

This is the frontier of the product made code. The verdict comes from one of two closed ways — an
inline threshold or the Rego package the challenge declares — and never from a language model. The
function is **pure**: no I/O, no clock, no identifiers; the activity around it does the talking to
OPA and the writing to the database. With sampling, the decision is taken on the upper bound of the
non-compliance proportion, so a small sample never absolves.

Four results (ADR-0007): `compliant`, `non_compliant`, `not_demonstrated` (the sample does
not allow absolving, with the sample size that would) and `inconclusive` (the probe failed
or the evidence does not answer the question). The canonical bytes of a verdict are fixed
by the suite of F05-03.
"""

import hashlib
import json
import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

from argos_challenges.sampling import required_sample_size, wilson_upper
from argos_common.journal import canonicalize

RESULTS = ("compliant", "non_compliant", "not_demonstrated", "inconclusive")
OPERATORS: Mapping[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
}
# The sampling projection is written with six decimals, rounded up: conservative and identical on
# every machine, because the canonical journal does not admit floating point numbers.
RATE_PRECISION = Decimal("0.000001")
COUNTING_FIELD = "count"
MISSING = object()


@dataclass(frozen=True, slots=True)
class Verdict:
    unit_id: str
    challenge_id: str
    challenge_version: str
    node_key: str
    result: str
    via: str
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "challenge_version": self.challenge_version,
            "detail": self.detail,
            "node_key": self.node_key,
            "result": self.result,
            "unit_id": self.unit_id,
            "via": self.via,
        }

    def canonical(self) -> str:
        return canonicalize(self.as_dict())

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


def _pluck(data: Any, path: str) -> Any:
    """The value of a dotted path (`rows.0.ssl`), or MISSING when the evidence does not have it."""
    current = data
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return MISSING
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit() or int(part) >= len(current):
                return MISSING
            current = current[int(part)]
        else:
            return MISSING
    return current


def _comparable(observed: Any, expected: Any) -> bool:
    if isinstance(observed, bool) or isinstance(expected, bool):
        return isinstance(observed, bool) and isinstance(expected, bool)
    if isinstance(observed, int | float) and isinstance(expected, int | float):
        return True
    return isinstance(observed, str) and isinstance(expected, str)


def _upper_rate(failures: int, sample: int, confidence: float) -> Decimal:
    bound = wilson_upper(failures, sample, confidence)
    return Decimal(repr(bound)).quantize(RATE_PRECISION, rounding=ROUND_CEILING)


def _projection(rate: Decimal, population: int) -> int:
    return int((rate * population).to_integral_value(rounding=ROUND_CEILING))


def _verdict(unit: Mapping[str, Any], result: str, via: str, detail: dict[str, Any]) -> Verdict:
    return Verdict(
        unit_id=str(unit["unit_id"]),
        challenge_id=str(unit["challenge_id"]),
        challenge_version=str(unit["challenge_version"]),
        node_key=str(unit["node_key"]),
        result=result,
        via=via,
        detail=detail,
    )


def _threshold_verdict(
    unit: Mapping[str, Any], threshold: Mapping[str, Any], observed: Any
) -> Verdict:
    field, op, expected = str(threshold["field"]), str(threshold["operator"]), threshold["value"]
    detail: dict[str, Any] = {
        "expected": expected,
        "field": field,
        "observed": observed,
        "operator": op,
    }
    if not _comparable(observed, expected):
        return _verdict(unit, "inconclusive", "type_mismatch", detail)

    sampling = unit.get("sampling")
    if not sampling or field != COUNTING_FIELD:
        holds = OPERATORS[op](observed, expected)
        return _verdict(unit, "compliant" if holds else "non_compliant", "threshold", detail)

    population = int(sampling["population"])
    sample = int(sampling["sample"])
    confidence = float(sampling["confidence"])
    failures = int(observed)
    rate = _upper_rate(failures, sample, confidence)
    projected = _projection(rate, population)
    detail["sampling"] = {
        "confidence": f"{confidence:.2f}",
        "failures": failures,
        "population": population,
        "projected_upper": projected,
        "sample": sample,
        "upper_rate": f"{rate:f}",
    }
    if not OPERATORS[op](failures, expected):
        # What the sample already shows is enough: no bound can absolve it.
        return _verdict(unit, "non_compliant", "threshold", detail)
    if OPERATORS[op](projected, expected):
        return _verdict(unit, "compliant", "threshold", detail)
    detail["sampling"]["required_sample"] = _required_sample(expected, population, confidence)
    return _verdict(unit, "not_demonstrated", "threshold", detail)


def _required_sample(expected: Any, population: int, confidence: float) -> int:
    """The sample that would demonstrate the threshold with no failures; a census when it is 0."""
    tolerated = int(expected) if isinstance(expected, int | float) else 0
    if tolerated <= 0:
        return population
    target = tolerated / population
    return min(population, required_sample_size(0, target, confidence))


def evaluate(
    unit: Mapping[str, Any],
    probe_result: Mapping[str, Any],
    opa_decision: Mapping[str, Any] | None = None,
    *,
    opa_input: Mapping[str, Any] | None = None,
) -> Verdict:
    """The verdict of a unit. Pure: the same inputs always give the same bytes.

    With `opa_input`, an OPA verdict carries the SHA-256 of what OPA saw, evidence included: two
    different pieces of evidence can no longer give the same verdict hash (SEC-013).
    """
    if not probe_result.get("ok", False):
        error = ""
        data = probe_result.get("data")
        if isinstance(data, Mapping):
            error = str(data.get("error", ""))
        return _verdict(unit, "inconclusive", "probe_error", {"error": error})

    criterion = unit["criterion"]
    data = probe_result.get("data", {})
    if "opa" in criterion:
        package = str(criterion["opa"]["package"])
        compliant = None if opa_decision is None else opa_decision.get("compliant")
        if not isinstance(compliant, bool):
            return _verdict(unit, "inconclusive", "opa_invalid", {"package": package})
        detail: dict[str, Any] = {"compliant": compliant, "package": package}
        if opa_input is not None:
            seen = json.dumps(opa_input, sort_keys=True, separators=(",", ":"), default=str)
            detail["input_sha256"] = hashlib.sha256(seen.encode("utf-8")).hexdigest()
        return _verdict(unit, "compliant" if compliant else "non_compliant", "opa", detail)

    threshold = criterion["threshold"]
    observed = _pluck(data, str(threshold["field"]))
    if observed is MISSING:
        return _verdict(unit, "inconclusive", "missing_field", {"field": str(threshold["field"])})
    return _threshold_verdict(unit, threshold, observed)
