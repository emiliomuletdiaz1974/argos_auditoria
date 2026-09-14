"""Aplica las migraciones pendientes.

Uso: uv run python tools/migrate.py [carpeta]   (por defecto services/api/migrations)
"""

import sys
from pathlib import Path

from argos_comun.config import get_config
from argos_comun.migraciones import aplicar


def main() -> int:
    carpeta = Path(sys.argv[1] if len(sys.argv) > 1 else "services/api/migrations")
    nuevas = aplicar(get_config().DATABASE_URL, carpeta)
    print(f"aplicadas: {nuevas or 'ninguna'} · esquema al día")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
