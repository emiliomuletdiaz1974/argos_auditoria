"""Write the trust file of the development verifier: the evidence key and the TSA root (ARG-069).

    uv run python tools/verifier_trust.py [--out deploy/dev/verifier/trust.json]

The public verifier believes only what its trust file names, never what a bundle carries. In an
installation that file comes from the issuer through a channel the verifier's owner trusts; in
development the key lives in a Vault started in dev mode, so it changes whenever Vault restarts and
`make dev` writes the file again. The verifier reads it on every request.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from argos_common.release import VaultTransitSigner
from argos_evidence.core.envelope import key_id

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "deploy" / "dev" / "verifier" / "trust.json"


def trust_document(vault: str, token: str, tsa_roots_url: str) -> dict[str, list[str]]:
    signer = VaultTransitSigner(vault, token, key="argos-evidence")
    root = httpx.get(tsa_roots_url, timeout=10)
    root.raise_for_status()
    return {"issuer_key_ids": [key_id(signer.public_key())], "tsa_roots_pem": [root.text]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--vault", default=os.environ.get("ARGOS_VAULT_ADDR", "http://127.0.0.1:8200")
    )
    parser.add_argument("--tsa-roots-url", default="http://127.0.0.1:3180/ca.pem")
    args = parser.parse_args(argv)
    token = os.environ.get("ARGOS_VAULT_TOKEN", "root")  # development Vault: -dev-root-token-id
    document = trust_document(args.vault, token, args.tsa_roots_url)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"verifier trust written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
