"""Check an evidence bundle without network, the same way the public verifier does (ARG-069).

    uv run python tools/verify_evidence.py bundle.json [--json report.json]

Exit code 0 when no check failed, 1 when one did, 2 when the bundle cannot be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from argos_verifier.checks import verify_bundle

MARKS = {"passed": "OK  ", "failed": "FAIL", "skipped": "--  "}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--json", type=Path, help="also write the report as JSON")
    args = parser.parse_args(argv)
    try:
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read the bundle: {exc}")
        return 2
    report = verify_bundle(bundle if isinstance(bundle, dict) else {})
    for check in report.checks:
        print(f"{MARKS[check.status]} {check.name}: {check.detail}")
    print("RESULT: " + ("verified" if report.ok else "NOT verified"))
    if args.json:
        args.json.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
