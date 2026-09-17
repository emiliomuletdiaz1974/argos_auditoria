"""Generate the challenge catalog from the library, or check that it is up to date (ARG-050)."""

import argparse
import sys
from pathlib import Path

from argos_challenges.library.catalog import build_catalog, catalog_yaml, load_library
from argos_ontology.traceability import load_challenge_catalog
from argos_ontology.vocabulary import LIBRARY_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=LIBRARY_DIR)
    parser.add_argument(
        "--check", action="store_true", help="fail if the catalog is not up to date"
    )
    args = parser.parse_args(argv)
    catalog_file = args.library / "challenges" / "catalog.yaml"

    reserved = load_challenge_catalog(catalog_file)
    entries = build_catalog(load_library(args.library / "challenges"), reserved)
    text = catalog_yaml(entries)
    drafts = sum(1 for entry in entries.values() if entry["draft"])
    current = catalog_file.read_text(encoding="utf-8")
    if args.check:
        if current != text:
            print(f"{catalog_file}: the catalog is not up to date", file=sys.stderr)
            return 1
        print(f"{len(entries)} challenge(s) in the catalog, {drafts} still reserved; up to date")
        return 0
    catalog_file.write_text(text, encoding="utf-8", newline="\n")
    print(f"{len(entries)} challenge(s) written, {drafts} still reserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
