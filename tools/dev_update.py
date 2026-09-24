"""The folders of the updater in the development environment (F09-10, ARG-086).

deploy/dev/update/ (gitignored) holds what the API and the updater share:
    inbox/        the bundles, as the esclusa of ARG-090 leaves them
    queue/        the requests the API accepted (POST /api/v1/system/updates)
    version       the installed version (the updater writes it)
    release.pub   the release key the API verifies with, taken from Vault transit (argos-release)

On the appliance the key is pinned in the image and the folders live on the node. The updater runs
on the host here (deviation note ARG-086):

    ARGOS_UPDATE_STATE=deploy/dev/update ARGOS_RELEASE_PUBLIC_KEY=deploy/dev/update/release.pub \
    ARGOS_COMPOSE_FILE=deploy/dev/compose.yaml uv run argos-update watch \
        --inbox deploy/dev/update/inbox --queue deploy/dev/update/queue
"""

import os
import stat
import sys
from pathlib import Path

from argos_common.release import VaultTransitSigner

ROOT = Path(__file__).resolve().parents[1]
UPDATE = ROOT / "deploy" / "dev" / "update"


def main() -> int:
    for folder in (UPDATE / "inbox", UPDATE / "queue"):
        folder.mkdir(parents=True, exist_ok=True)
    # The API writes the queue as the user of its container (10001). Open in development only: a
    # request someone writes by hand gains nothing, the updater verifies the bundle anyway.
    os.chmod(UPDATE / "queue", stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)  # noqa: S103
    version = UPDATE / "version"
    if not version.exists():
        version.write_text((ROOT / "VERSION").read_text(encoding="utf-8").strip(), encoding="utf-8")
    signer = VaultTransitSigner(os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200"), "root")
    (UPDATE / "release.pub").write_bytes(signer.public_key())
    print(f"updater folders and release key in {UPDATE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
