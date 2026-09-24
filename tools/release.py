"""Release manifest (ARG-010).

uv run python tools/release.py build --version 0.1.0 [--sbom dist/sbom]
uv run python tools/release.py sign      # uses VAULT_ADDR and VAULT_TOKEN
uv run python tools/release.py verify    # offline, with dist/release.pub
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from argos_common import security_log
from argos_common.errors import IntegrityError
from argos_common.release import (
    VaultTransitSigner,
    build_manifest,
    key_fingerprint,
    require_trusted_key,
    serialize,
    verify_release_files,
    verify_signature,
)

DIST = Path("dist")
MANIFEST = DIST / "release-manifest.json"
SIGNATURE = DIST / "release-manifest.sig"
PUBLIC_KEY = DIST / "release.pub"


def _images(version: str) -> list[dict[str, str]]:
    listing = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            "image",
            "ls",
            "--filter",
            f"label=org.argos.version={version}",
            "--format",
            "{{json .}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    images = []
    for line in filter(None, listing.splitlines()):
        img = json.loads(line)
        inspected = json.loads(
            subprocess.run(  # noqa: S603
                ["docker", "image", "inspect", img["ID"]],  # noqa: S607
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )[0]
        component = inspected["Config"]["Labels"].get("org.argos.component", "unknown")
        images.append(
            {"ref": f"{img['Repository']}:{img['Tag']}@{inspected['Id']}", "component": component}
        )
    if not images:
        raise SystemExit(f"no images labelled org.argos.version={version}: run make build")
    return images


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--version", required=True)
    build.add_argument("--sbom", type=Path, default=DIST / "sbom")
    sub.add_parser("sign")
    verify = sub.add_parser("verify")
    verify.add_argument("--fingerprint", help="or ARGOS_RELEASE_KEY_FINGERPRINT")
    args = parser.parse_args()

    if args.command == "build":
        DIST.mkdir(exist_ok=True)
        built_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = build_manifest(args.version, _images(args.version), args.sbom, built_at)
        MANIFEST.write_bytes(serialize(manifest))
        print(f"manifest written to {MANIFEST}")
    elif args.command == "sign":
        signer = VaultTransitSigner(os.environ["VAULT_ADDR"], os.environ["VAULT_TOKEN"])
        SIGNATURE.write_bytes(signer.sign(MANIFEST.read_bytes()))
        PUBLIC_KEY.write_bytes(signer.public_key())
        print(f"signature in {SIGNATURE}, public key in {PUBLIC_KEY}")
        print(f"key fingerprint {key_fingerprint(signer.public_key())}: record it apart from dist/")
    else:
        # The key sits beside the manifest in dist/: it is trusted only by a fingerprint kept apart.
        public_key = PUBLIC_KEY.read_bytes()
        fingerprint = args.fingerprint or os.environ.get("ARGOS_RELEASE_KEY_FINGERPRINT")
        try:
            require_trusted_key(public_key, fingerprint)
            verify_signature(MANIFEST.read_bytes(), SIGNATURE.read_bytes(), public_key)
            # F09-09: the SBOMs and vulnerability reports beside it, covered by its hashes.
            verify_release_files(json.loads(MANIFEST.read_bytes()), DIST / "sbom")
        except IntegrityError as refused:
            # F09-08: where there is a database to record in (the appliance, the development
            # environment), the refused release stays in the security log.
            if os.environ.get("ARGOS_DATABASE_URL"):
                security_log.configure(os.environ["ARGOS_DATABASE_URL"])
            security_log.record(
                "release.signature_rejected",
                "system:release",
                "refused",
                {
                    "version": str(json.loads(MANIFEST.read_bytes()).get("version", ""))[:40],
                    "reason": str(refused)[:200],
                },
                source="argos-release",
            )
            raise
        print("valid signature")
    return 0


if __name__ == "__main__":
    sys.exit(main())
