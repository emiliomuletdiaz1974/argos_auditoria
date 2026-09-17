"""Run the five editorial gates of the ontology (ARG-038); nothing is published unless all pass.

Usage: uv run python tools/ontology_gates.py [--library DIR]
"""

import argparse
import sys
from pathlib import Path

from argos_ontology.gates import run_gates
from argos_ontology.vocabulary import LIBRARY_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the five ontology editorial gates.")
    parser.add_argument("--library", type=Path, default=LIBRARY_DIR)
    args = parser.parse_args(argv)
    results = run_gates(args.library)
    for result in results:
        print(f"{'PASS' if result.ok else 'FAIL'} {result.name}")
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
