"""Generates the v1 contract from the application and keeps the versioned file honest (ARG-071).

`--check` compares and fails when they diverge; without it, writes the file. The contract is not
documentation written aside: it comes from the routes, so a route that changes changes the contract.
"""

import argparse
import json
import sys
from pathlib import Path

from argos_api.app import create_app

CONTRACT = Path(__file__).resolve().parents[1] / "services" / "api" / "openapi.json"


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the file is not up to date")
    args = parser.parse_args(argv)

    generated = render()
    if not args.check:
        CONTRACT.write_text(generated, encoding="utf-8")
        print(f"written {CONTRACT}")
        return 0

    current = CONTRACT.read_text(encoding="utf-8") if CONTRACT.exists() else ""
    if current == generated:
        print("the v1 contract is up to date")
        return 0
    print("the v1 contract does not match the application: run `make api-contract-write`")
    return 1


if __name__ == "__main__":
    sys.exit(main())
