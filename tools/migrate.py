"""Apply pending migrations.

Usage: uv run python tools/migrate.py [directory]   (defaults to services/api/migrations)
"""

import sys
from pathlib import Path

from argos_common.config import get_config
from argos_common.migrations import apply_migrations


def main() -> int:
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "services/api/migrations")
    applied = apply_migrations(get_config().DATABASE_URL, directory)
    print(f"applied: {applied or 'none'} - schema up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
