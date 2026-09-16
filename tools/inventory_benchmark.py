"""Run the inventory capacity benchmark on a throw-away database (Especificación §3.10).

Usage: uv run --env-file .env.example python tools/inventory_benchmark.py [--profile smoke|s|m]
       [--output PATH] [--keep]
"""

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from argos_common.config import get_config
from argos_common.migrations import apply_migrations
from argos_inventory.benchmark import PROFILES, run_benchmark

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "services" / "api" / "migrations"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the inventory capacity benchmark.")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument("--output", type=Path, help="write the JSON report here instead of stdout")
    parser.add_argument("--keep", action="store_true", help="keep the benchmark database")
    args = parser.parse_args(argv)

    admin_dsn = get_config().DATABASE_URL
    name = f"argos_bench_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = f"{admin_dsn.rsplit('/', 1)[0]}/{name}"
    try:
        apply_migrations(dsn, MIGRATIONS_DIR)
        report: dict[str, Any] = {
            "database": name if args.keep else None,
            **run_benchmark(dsn, PROFILES[args.profile]),
        }
    finally:
        if not args.keep:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
                conn.execute(drop.format(sql.Identifier(name)))

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"benchmark report written to {args.output}")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
