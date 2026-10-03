"""K-03 · creates the missing secrets of the bench in argos-core, and never shows a value.

It talks to the API of Kubernetes with the token of its own service account, which may only read and
create secrets in argos-core (rbac.yaml). A secret that exists is left as it is: running it again
changes nothing, and nobody, the repository included, ever sees a value. The list of what to
create is `secrets.yaml`, next to this script.
"""

import base64
import json
import secrets
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
API = "https://kubernetes.default.svc"
NAMESPACE = "argos-core"
WANTED = Path(__file__).with_name("secrets.yaml")


def _wanted() -> list[tuple[str, list[str]]]:
    """The list in secrets.yaml: `- name: x` and `keys: [a, b]`, in the only shape it uses."""
    found: list[tuple[str, list[str]]] = []
    for line in WANTED.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- name:"):
            found.append((line.split(":", 1)[1].strip(), []))
        elif line.startswith("keys:") and found:
            keys = line.split(":", 1)[1].strip().strip("[]")
            found[-1][1].extend(k.strip() for k in keys.split(",") if k.strip())
    return found


def _request(method: str, path: str, body: dict[str, object] | None = None) -> int:
    token = (ACCOUNT / "token").read_text(encoding="utf-8").strip()
    context = ssl.create_default_context(cafile=str(ACCOUNT / "ca.crt"))
    request = urllib.request.Request(  # noqa: S310 - a fixed https address
        f"{API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, context=context, timeout=20) as answer:  # noqa: S310
            return int(answer.status)
    except urllib.error.HTTPError as refused:
        return int(refused.code)


def main() -> int:
    created = kept = 0
    for name, keys in _wanted():
        path = f"/api/v1/namespaces/{NAMESPACE}/secrets"
        status = _request("GET", f"{path}/{name}")
        if status == 200:
            kept += 1
            continue
        if status != 404:
            print(f"{name}: the API answered {status}", file=sys.stderr)
            return 1
        data = {
            str(key): base64.b64encode(secrets.token_urlsafe(32).encode()).decode() for key in keys
        }
        secret: dict[str, object] = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": name, "labels": {"argos/generated": "true"}},
            "type": "Opaque",
            "data": data,
        }
        status = _request("POST", path, secret)
        if status != 201:
            print(f"{name}: not created, the API answered {status}", file=sys.stderr)
            return 1
        created += 1
        print(f"{name}: created")
    print(f"done: {created} created, {kept} already there")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
