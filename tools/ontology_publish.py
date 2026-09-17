"""Build, sign and verify ontology bundles (ARG-040); publishing is one command, not a ritual.

Usage:
  uv run --env-file .env.example python tools/ontology_publish.py build --version 1.0.0
         --in-force-from 2026-10-01 [--output dist/ontology]
  uv run python tools/ontology_publish.py verify dist/ontology/argos-ontology-1.0.0.tar.gz

build signs with the Vault transit key argos-content (ARGOS_VAULT_ADDR and a token with signing
rights in ARGOS_VAULT_TOKEN) and writes the bundle, its signature and the content public key.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from argos_common.config import get_config
from argos_common.release import VaultTransitSigner
from argos_ontology.bundle import (
    CONTENT_KEY,
    BundleRejectedError,
    build_bundle,
    sign_bundle,
    verify_bundle,
)
from argos_ontology.vocabulary import LIBRARY_DIR

DIST = Path("dist") / "ontology"
PUBLIC_KEY_NAME = "content.pub"


def signature_path(bundle: Path) -> Path:
    return bundle.with_name(f"{bundle.name}.sig")


def _build(args: argparse.Namespace) -> int:
    cfg = get_config()
    if cfg.VAULT_TOKEN is None:
        print("ARGOS_VAULT_TOKEN is required to sign", file=sys.stderr)
        return 2
    signer = VaultTransitSigner(cfg.VAULT_ADDR, cfg.VAULT_TOKEN.get_secret_value(), key=CONTENT_KEY)
    bundle, manifest = build_bundle(
        args.library, args.version, date.fromisoformat(args.in_force_from)
    )
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / f"argos-ontology-{args.version}.tar.gz"
    target.write_bytes(bundle)
    signature_path(target).write_bytes(sign_bundle(manifest, signer))
    (args.output / PUBLIC_KEY_NAME).write_bytes(signer.public_key())
    print(f"published {target} ({len(manifest['files'])} files)")
    return 0


def _verify(args: argparse.Namespace) -> int:
    bundle = args.bundle.read_bytes()
    signature = signature_path(args.bundle).read_bytes()
    public_key = (args.public_key or args.bundle.parent / PUBLIC_KEY_NAME).read_bytes()
    try:
        verified = verify_bundle(bundle, signature, public_key)
    except BundleRejectedError as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 1
    print(f"verified {verified.version}, in force from {verified.in_force_from.isoformat()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build, sign and verify ontology bundles.")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--version", required=True)
    build.add_argument("--in-force-from", required=True)
    build.add_argument("--library", type=Path, default=LIBRARY_DIR)
    build.add_argument("--output", type=Path, default=DIST)
    verify = commands.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    verify.add_argument("--public-key", type=Path)
    args = parser.parse_args(argv)
    return _build(args) if args.command == "build" else _verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
