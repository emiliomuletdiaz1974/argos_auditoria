"""Compile editorial obligation templates into canonical Turtle (ARG-038).

Usage: uv run python tools/ontology_compile.py [--check] [SOURCE_DIR] [OUTPUT_DIR]

Without --check it writes one <id>.ttl per template; with --check it writes nothing and fails when
a generated file is missing or differs, which is how the syntax gate proves the Turtle is current.
"""

import argparse
import sys
from pathlib import Path

from argos_ontology.editorial.compiler import compile_file
from argos_ontology.vocabulary import LIBRARY_DIR

SOURCE_DIR = LIBRARY_DIR / "ontology" / "editorial"
OUTPUT_DIR = LIBRARY_DIR / "ontology" / "norms" / "generated"
TEMPLATE_NAME = "obligation-template.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile editorial templates to Turtle.")
    parser.add_argument("--check", action="store_true", help="fail if generated Turtle is stale")
    parser.add_argument("source", nargs="?", type=Path, default=SOURCE_DIR)
    parser.add_argument("output", nargs="?", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    stale: list[str] = []
    templates = sorted(p for p in args.source.glob("*.yaml") if p.name != TEMPLATE_NAME)
    for template in templates:
        turtle = compile_file(template)
        target = args.output / f"{template.stem}.ttl"
        if args.check:
            if not target.is_file() or target.read_bytes() != turtle:
                stale.append(target.name)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(turtle)
    if stale:
        print(f"stale or missing generated Turtle: {stale}", file=sys.stderr)
        return 1
    print(f"{len(templates)} template(s) {'checked' if args.check else 'compiled'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
