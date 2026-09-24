"""Settings shared by every test under tests/."""

import os
from pathlib import Path

# F09-04: the development database asks for a password over the network. Tests connect as its
# superuser with the development-only one, unless the caller brings its own.
os.environ.setdefault("PGPASSWORD", "dev-only-postgres")

# F09-06: NATS asks every client for a certificate; tests present the host one that `make dev`
# issues (tools/dev_tls.py). PostgreSQL speaks TLS only and libpq negotiates it by default; that the
# server is verified is checked in test_mtls.py. PGSSLMODE is never set: it would also reach the
# sources of the client, whose TLS each connector decides (F09-31).
_HOST_TLS = Path(__file__).resolve().parents[1] / "deploy" / "dev" / "secrets" / "tls-host"
os.environ.setdefault("ARGOS_TLS_DIR", str(_HOST_TLS))
