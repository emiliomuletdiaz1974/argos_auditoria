"""K-03 · creates the missing secrets of the bench in argos-core, and never shows a value.

It talks to the API of Kubernetes with the token of its own service account, which may only read and
create secrets in argos-core (rbac.yaml). A secret that exists is left as it is: running it again
changes nothing, and nobody, the repository included, ever sees a value. The list of what to
create is `secrets.yaml`, next to this script.

K-06: a pod reads secrets only of its own namespace. A secret with `copy_to` is copied, with the
same values, to each namespace listed (the services of argos-services sign in to NATS with the
passwords the server of argos-core knows). A copy that exists is left as it is, like the original.
"""

import base64
import json
import secrets
import ssl
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
API = "https://kubernetes.default.svc"
NAMESPACE = "argos-core"
WANTED = Path(__file__).with_name("secrets.yaml")


def _list(text: str) -> list[str]:
    return [k.strip() for k in text.split(":", 1)[1].strip().strip("[]").split(",") if k.strip()]


def _wanted() -> list[tuple[str, list[str], list[str]]]:
    """The list in secrets.yaml: `- name: x`, `keys: [a, b]` and an optional `copy_to: [ns]`."""
    found: list[tuple[str, list[str], list[str]]] = []
    for line in WANTED.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- name:"):
            found.append((line.split(":", 1)[1].strip(), [], []))
        elif line.startswith("keys:") and found:
            found[-1][1].extend(_list(line))
        elif line.startswith("copy_to:") and found:
            found[-1][2].extend(_list(line))
    return found


def _request(
    method: str, path: str, body: dict[str, object] | None = None
) -> tuple[int, dict[str, Any]]:
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
            return int(answer.status), json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as refused:
        return int(refused.code), {}


def _ensure(namespace: str, name: str, data: Callable[[], dict[str, str]]) -> str | None:
    """`kept`, `created` or None when the API said something else (already reported)."""
    path = f"/api/v1/namespaces/{namespace}/secrets"
    status, _ = _request("GET", f"{path}/{name}")
    if status == 200:
        return "kept"
    if status != 404:
        print(f"{namespace}/{name}: the API answered {status}", file=sys.stderr)
        return None
    secret: dict[str, object] = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "labels": {"argos/generated": "true"}},
        "type": "Opaque",
        "data": data(),
    }
    status, _ = _request("POST", path, secret)
    if status != 201:
        print(f"{namespace}/{name}: not created, the API answered {status}", file=sys.stderr)
        return None
    print(f"{namespace}/{name}: created")
    return "created"


def _random(keys: list[str]) -> Callable[[], dict[str, str]]:
    return lambda: {
        str(key): base64.b64encode(secrets.token_urlsafe(32).encode()).decode() for key in keys
    }


def _original(name: str) -> Callable[[], dict[str, str]]:
    def read() -> dict[str, str]:
        status, body = _request("GET", f"/api/v1/namespaces/{NAMESPACE}/secrets/{name}")
        if status != 200:
            raise RuntimeError(f"{name}: the original could not be read ({status})")
        return dict(body["data"])

    return read


def main() -> int:
    counts = {"created": 0, "kept": 0}
    for name, keys, copy_to in _wanted():
        for namespace, data in [
            (NAMESPACE, _random(keys)),
            *((target, _original(name)) for target in copy_to),
        ]:
            outcome = _ensure(namespace, name, data)
            if outcome is None:
                return 1
            counts[outcome] += 1
    print(f"done: {counts['created']} created, {counts['kept']} already there")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
