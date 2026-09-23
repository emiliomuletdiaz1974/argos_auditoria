"""Settings shared by every test under tests/."""

import os

# F09-04: the development database asks for a password over the network. Tests connect as its
# superuser with the development-only one, unless the caller brings its own.
os.environ.setdefault("PGPASSWORD", "dev-only-postgres")
