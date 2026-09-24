"""ARG-081 · the CIS gate of the appliance image (F09-14).

    uv run python tools/cis_gate.py --report cis-report.json \
        [--exceptions platform/image/hardening-exceptions.yaml] [--threshold 90]

Reads the report of the scanner of the image (CIS Ubuntu Linux 24.04 LTS, Level 1 Server) and the
documented exceptions, and fails when:

- the score is below the threshold (90 % by contract): passed checks over passed and failed ones;
  checks that do not apply or were not selected do not count;
- a check failed and nobody accepted that failure in writing.

An exception is refused unless it says which check, why, and who accepted it: an exception without
its reason would hide a deviation, which is worse than documenting it. The exceptions do not raise
the score; they only let a known failure through.

The report is JSON, `{"checks": [{"id", "title", "result"}]}` with results `pass`, `fail`,
`notapplicable`, `notselected`, `error`, `informational`; the scan of the real image (F09-90)
converts the output of its scanner to it.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
EXCEPTIONS = REPO / "platform" / "image" / "hardening-exceptions.yaml"
THRESHOLD = 90.0
REQUIRED = ("id", "justification", "accepted_by")


class ExceptionsError(ValueError):
    """The exceptions file is not acceptable as it is."""


@dataclass
class Verdict:
    score: float
    passed: bool
    unaccepted: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def load_exceptions(path: Path) -> dict[str, dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    loaded: dict[str, dict[str, Any]] = {}
    for n, entry in enumerate(document.get("exceptions") or [], start=1):
        for key in REQUIRED:
            if not str((entry or {}).get(key) or "").strip():
                raise ExceptionsError(f"exception {n} has no {key}")
        loaded[str(entry["id"])] = entry
    return loaded


def decide(report: Path, exceptions: Path, threshold: float = THRESHOLD) -> Verdict:
    accepted = load_exceptions(exceptions)
    checks = json.loads(report.read_text(encoding="utf-8"))["checks"]
    passed = [c for c in checks if c["result"] == "pass"]
    failed = [c for c in checks if c["result"] in ("fail", "error")]
    counted = len(passed) + len(failed)
    score = 100.0 * len(passed) / counted if counted else 0.0
    unaccepted = [str(c["id"]) for c in failed if str(c["id"]) not in accepted]
    errors = []
    if score < threshold:
        errors.append(f"score {score:.1f} % is below the threshold of {threshold:.0f} %")
    if unaccepted:
        errors.append(f"{len(unaccepted)} failed checks nobody accepted: {', '.join(unaccepted)}")
    return Verdict(score, not errors, unaccepted, errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--exceptions", type=Path, default=EXCEPTIONS)
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    args = parser.parse_args(argv)
    try:
        verdict = decide(args.report, args.exceptions, args.threshold)
    except ExceptionsError as broken:
        print(f"hardening exceptions refused: {broken}", file=sys.stderr)
        return 2
    print(f"CIS score: {verdict.score:.1f} % (threshold {args.threshold:.0f} %)")
    for error in verdict.errors:
        print(f"  - {error}")
    print("image accepted" if verdict.passed else "image refused")
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
