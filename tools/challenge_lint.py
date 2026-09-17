"""Validate every challenge of the library against the schema and the product rules (ARG-041)."""

import argparse
import sys
from pathlib import Path

from argos_challenges.dsl import (
    CHALLENGES_DIR,
    ChallengeError,
    LintContext,
    library_challenges,
    lint_challenge,
    load_challenge_file,
)
from argos_challenges.library.translation import TranslationError
from argos_ontology.vocabulary import LIBRARY_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=LIBRARY_DIR)
    parser.add_argument("--challenges", type=Path, default=None)
    args = parser.parse_args(argv)
    challenges_dir = args.challenges or (args.library / "challenges" if args.library else None)
    challenges_dir = challenges_dir or CHALLENGES_DIR

    context = LintContext.from_library(args.library)
    errors: list[str] = []
    paths = library_challenges(challenges_dir)
    for path in paths:
        try:
            spec = load_challenge_file(path)
        except (ChallengeError, TranslationError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        errors.extend(f"{path}: {message}" for message in lint_challenge(spec, context))
    for error in errors:
        print(error, file=sys.stderr)
    print(f"{len(paths)} challenge(s) checked; {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
