"""Write the obligation-challenge traceability matrix and fail on its errors (ARG-037).

Usage: uv run python tools/ontology_traceability.py [--library DIR] [--output DIR]

Writes traceability.json (console) and traceability.csv (contract annex) and exits with 1 when an
obligation has no challenge nor pending reason, a challenge is missing from the catalog, or a
catalog challenge has no obligation.
"""

import argparse
import sys
from pathlib import Path

from argos_ontology.traceability import (
    build_matrix,
    library_graph,
    load_challenge_catalog,
    matrix_csv,
    matrix_json,
)
from argos_ontology.vocabulary import LIBRARY_DIR

OUTPUT_DIR = Path("dist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the traceability matrix.")
    parser.add_argument("--library", type=Path, default=LIBRARY_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    catalog = load_challenge_catalog(args.library / "challenges" / "catalog.yaml")
    rows, errors = build_matrix(library_graph(args.library), catalog)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "traceability.json").write_text(matrix_json(rows), encoding="utf-8")
    (args.output / "traceability.csv").write_text(matrix_csv(rows), encoding="utf-8")
    covered = sum(1 for row in rows if row.status == "covered")
    print(f"{len(rows)} obligation(s), {covered} covered, {len(catalog)} catalog challenge(s)")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
