"""Write the overlap matrix between norms (ARG-038).

Usage: uv run python tools/ontology_overlap.py [--library DIR] [--output DIR]

Writes overlap.json (console) and overlap.csv (contract annex): the asset classes where one
campaign produces verdicts for obligations of several norms.
"""

import argparse
from pathlib import Path

from argos_ontology.overlap import build_overlap, overlap_csv, overlap_json
from argos_ontology.traceability import library_graph
from argos_ontology.vocabulary import LIBRARY_DIR

OUTPUT_DIR = Path("dist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the overlap matrix between norms.")
    parser.add_argument("--library", type=Path, default=LIBRARY_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    rows = build_overlap(library_graph(args.library))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "overlap.json").write_text(overlap_json(rows), encoding="utf-8")
    (args.output / "overlap.csv").write_text(overlap_csv(rows), encoding="utf-8")
    print(f"{len(rows)} asset class(es) shared by several norms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
