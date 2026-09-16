"""Write the readable inventory report (ARG-026).

Usage: uv run --env-file .env.example python tools/inventory_report.py
       [--output PATH] [--no-refresh]
"""

import argparse
import sys
from pathlib import Path

from argos_common.config import get_config
from argos_inventory.catalog.report import render_inventory_report
from argos_inventory.catalog.views import refresh_catalog
from argos_inventory.graph.store import GraphStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the readable inventory report.")
    parser.add_argument(
        "--output", type=Path, help="write the report to this file instead of stdout"
    )
    parser.add_argument(
        "--no-refresh", action="store_true", help="do not refresh the catalog first"
    )
    args = parser.parse_args(argv)
    dsn = get_config().DATABASE_URL
    if not args.no_refresh:
        refresh_catalog(dsn)
    report = render_inventory_report(GraphStore(dsn), dsn)
    if args.output is not None:
        args.output.write_text(report, encoding="utf-8")
        print(f"inventory report written to {args.output}")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
