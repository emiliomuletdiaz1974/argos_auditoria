"""K-06 · writes what the public verifier of the bench trusts: the evidence key and the TSA root.

The verifier believes only its trust file, never what a bundle carries (ARG-069), and it reaches no
other service. This Job takes the public key of `argos-evidence` from Vault (signed in with its own
service account, which may read that key and nothing else) and the root of the test TSA, and leaves
them in the ConfigMap `verifier-trust` that the verifier mounts and reads on every request. It is
what tools/verifier_trust.py does in the development environment.
"""

import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from argos_common.release import VaultTransitSigner
from argos_common.vault_auth import Renewing, kubernetes_login
from argos_evidence.core.envelope import key_id

VAULT = "http://vault.argos-core.svc:8200"
TSA_ROOT = "http://tsa.argos-core.svc:3180/ca.pem"
ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
API = "https://kubernetes.default.svc"
NAMESPACE = "argos-services"
NAME = "verifier-trust"


def trust_document(public_key: bytes, tsa_root_pem: str) -> dict[str, list[str]]:
    return {"issuer_key_ids": [key_id(public_key)], "tsa_roots_pem": [tsa_root_pem]}


def config_map(document: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": NAME, "namespace": NAMESPACE, "labels": {"argos/generated": "true"}},
        "data": {"trust.json": json.dumps(document, indent=2) + "\n"},
    }


def _kubernetes(method: str, path: str, body: dict[str, Any] | None = None) -> int:
    token = (ACCOUNT / "token").read_text(encoding="utf-8").strip()
    request = urllib.request.Request(  # noqa: S310 - a fixed https address
        f"{API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    context = ssl.create_default_context(cafile=str(ACCOUNT / "ca.crt"))
    try:
        with urllib.request.urlopen(request, context=context, timeout=20) as answer:  # noqa: S310
            return int(answer.status)
    except urllib.error.HTTPError as refused:
        return int(refused.code)


def main() -> int:
    token = Renewing(kubernetes_login(VAULT, NAME, ACCOUNT / "token"))
    public_key = VaultTransitSigner(VAULT, token, key="argos-evidence").public_key()
    with urllib.request.urlopen(TSA_ROOT, timeout=20) as answer:  # noqa: S310 - fixed address
        tsa_root = answer.read().decode("utf-8")
    body = config_map(trust_document(public_key, tsa_root))
    path = f"/api/v1/namespaces/{NAMESPACE}/configmaps"
    exists = _kubernetes("GET", f"{path}/{NAME}") == 200
    if exists:
        status = _kubernetes("PUT", f"{path}/{NAME}", body)
    else:
        status = _kubernetes("POST", path, body)
    if status not in (200, 201):
        print(f"{NAME}: the API answered {status}", file=sys.stderr)
        return 1
    print(f"{NAME}: written for key {key_id(public_key)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
