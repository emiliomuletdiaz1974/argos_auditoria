"""The folders of the airlock in the development environment (F09-13, ARG-090).

deploy/dev/airgap/ (gitignored) stands for the removable medium and the work zone:
    in/           what comes in; the API sees it read-only
    out/          what goes out, one folder per export
    work/         where each file is copied and checked before an importer sees it
    content.pub   the content key the API verifies normative bundles with, taken from Vault
                  transit (argos-content)

On the appliance the medium is mounted read-only by udev and remounted to write only while an
export runs (F09-92); the content key is pinned in the image.
"""

import os
import stat
import sys
from pathlib import Path

from argos_common.release import VaultTransitSigner
from argos_ontology.bundle import CONTENT_KEY

ROOT = Path(__file__).resolve().parents[1]
AIRGAP = ROOT / "deploy" / "dev" / "airgap"


def main() -> int:
    for name in ("in", "out", "work"):
        folder = AIRGAP / name
        folder.mkdir(parents=True, exist_ok=True)
        # The API writes out/ and work/ as the user of its container (10001). Open in development
        # only: whatever is dropped by hand in in/ is verified like anything else.
        os.chmod(folder, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)  # noqa: S103
    signer = VaultTransitSigner(
        os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200"), "root", key=CONTENT_KEY
    )
    (AIRGAP / "content.pub").write_bytes(signer.public_key())
    print(f"airlock folders and content key in {AIRGAP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
