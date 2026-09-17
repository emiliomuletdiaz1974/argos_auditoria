"""OPA client: one call, one structured verdict (ARG-036).

Operational decisions that are not a plain numeric threshold (does this retention fit the approved
schedule, are these identities authorized for a special category) live as Rego packages in
`library/policies/`. Each package exposes a `verdict` object; the challenge evaluator passes the
probe evidence as `input` and the client's approved parameters are loaded as `data.client`.
"""

import re
from typing import Any

import httpx

DEFAULT_OPA_URL = "http://127.0.0.1:8181"
PACKAGE_NAME = re.compile(r"^argos(\.[a-z_]+)+$")
TIMEOUT_SECONDS = 5.0


class OpaError(RuntimeError):
    """OPA could not be reached or did not return a verdict object."""


def evaluate(
    package: str,
    input_doc: dict[str, Any],
    base_url: str = DEFAULT_OPA_URL,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """The `verdict` of a Rego package for this input."""
    if not PACKAGE_NAME.fullmatch(package):
        raise ValueError(f"invalid Rego package name: {package!r}")
    url = f"{base_url.rstrip('/')}/v1/data/{package.replace('.', '/')}/verdict"
    owned = client is None
    http = client if client is not None else httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        response = http.post(url, json={"input": input_doc})
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        raise OpaError(f"OPA answered {exc.response.status_code} for {package}") from exc
    except httpx.HTTPError as exc:
        raise OpaError(f"cannot reach OPA at {base_url}: {exc}") from exc
    finally:
        if owned:
            http.close()
    result = body.get("result") if isinstance(body, dict) else None
    if result is None:
        raise OpaError(f"Rego package without verdict: {package}")
    if not isinstance(result, dict):
        raise OpaError(f"verdict of {package} is not an object")
    return result
