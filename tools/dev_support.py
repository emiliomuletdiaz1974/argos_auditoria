"""The folder of the diagnostic packages in the development environment (F09-11, ARG-088).

deploy/dev/support/ (gitignored) holds what the API and the collector share:
    queue/          the requests the API accepted (POST /api/v1/support/diagnostics)
    previews/       the previews the collector left, to review before anything leaves
    support.pub     the age public key the API encrypts for
    support.key     its private key: in development only, so the tests can open a package

On the appliance only the public key of support is there, pinned in the image. The collector runs
on the host here, next to Docker Compose (like the updater, note ARG-086):

    ARGOS_COMPOSE_FILE=deploy/dev/compose.yaml ARGOS_UPDATE_STATE=deploy/dev/update \
    uv run argos-support watch --store deploy/dev/support
"""

import os
import stat
import sys
from pathlib import Path

import pyrage

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "deploy" / "dev" / "support"


def main() -> int:
    for folder in (SUPPORT / "queue", SUPPORT / "previews"):
        folder.mkdir(parents=True, exist_ok=True)
        # The API writes the queue as the user of its container (10001). Open in development only:
        # a request written by hand gains nothing, and a preview edited by hand no longer matches
        # its index, so the API refuses to package it.
        os.chmod(folder, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)  # noqa: S103
    key = SUPPORT / "support.key"
    if not key.exists():
        identity = pyrage.x25519.Identity.generate()
        key.write_text(f"{identity}\n", encoding="utf-8")
        (SUPPORT / "support.pub").write_text(f"{identity.to_public()}\n", encoding="utf-8")
    print(f"diagnostics folders and the test key of support in {SUPPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
