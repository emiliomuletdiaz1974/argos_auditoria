"""K-06 · how a service signs in to Vault (ADR-0014, point 3).

In the cluster a service signs in with the token of its Kubernetes service account, which the
kubelet mounts and rotates; Vault checks it with the API of the cluster and answers a token with the
policies of the service's role. Nobody hands the service a Vault token. Out of the cluster nothing
changes: the database credential signs in with an AppRole delivered as files, and the rest uses the
fixed token of the configuration, if any.

A login answers a token and how long it lives. `Renewing` keeps it and signs in again a minute
before it expires (at half the life of a short one), so a service that reads secrets or signs for
days never holds an expired token. Nothing here writes a token or the account's JWT to a log.
"""

import json
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import ArgosConfig

Login = Callable[[], tuple[str, float]]
RENEW_BEFORE = 60.0


def vault_request(addr: str, path: str, token: str | None, body: Any = None) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - the address comes from the configuration
        f"{addr.rstrip('/')}/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json", **({"X-Vault-Token": token} if token else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            answer: dict[str, Any] = json.loads(response.read())
    except OSError as exc:  # the message names the path, never a secret
        raise ConnectionError(f"vault did not answer {path}: {type(exc).__name__}") from None
    return answer


def _token_of(answer: dict[str, Any]) -> tuple[str, float]:
    auth = answer["auth"]
    return str(auth["client_token"]), float(auth["lease_duration"])


def kubernetes_login(addr: str, role: str, jwt_file: Path) -> Login:
    """Signs in with the service account; the JWT is read each time, as the kubelet rotates it."""

    def login() -> tuple[str, float]:
        jwt = jwt_file.read_text(encoding="utf-8").strip()
        return _token_of(
            vault_request(addr, "auth/kubernetes/login", None, {"role": role, "jwt": jwt})
        )

    return login


def approle_login(addr: str, approle_dir: Path) -> Login:
    """Signs in with the AppRole delivered as files, never as variables."""

    def login() -> tuple[str, float]:
        role_id = (approle_dir / "role_id").read_text(encoding="utf-8").strip()
        secret_id = (approle_dir / "secret_id").read_text(encoding="utf-8").strip()
        return _token_of(
            vault_request(
                addr, "auth/approle/login", None, {"role_id": role_id, "secret_id": secret_id}
            )
        )

    return login


class Renewing:
    """The token of a login, kept while it is good and asked for again before it expires."""

    def __init__(self, login: Login, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._login = login
        self._clock = clock
        self._token = ""
        self._renew_at = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            if not self._token or self._clock() >= self._renew_at:
                token, ttl = self._login()
                delay = ttl - RENEW_BEFORE if ttl >= 2 * RENEW_BEFORE else ttl / 2
                self._token, self._renew_at = token, self._clock() + delay
            return self._token

    def __repr__(self) -> str:
        return "Renewing(<token hidden>)"


def _kubernetes(cfg: ArgosConfig) -> Login | None:
    if not cfg.VAULT_KUBERNETES_ROLE:
        return None
    return kubernetes_login(
        cfg.VAULT_ADDR, cfg.VAULT_KUBERNETES_ROLE, Path(cfg.VAULT_KUBERNETES_TOKEN_FILE)
    )


def service_token(cfg: ArgosConfig) -> Callable[[], str]:
    """The token for the secrets and the signing of the service: its account, or the fixed one."""
    login = _kubernetes(cfg)
    if login is not None:
        return Renewing(login)
    fixed = cfg.VAULT_TOKEN.get_secret_value() if cfg.VAULT_TOKEN else ""
    return lambda: fixed


def database_login(cfg: ArgosConfig) -> Callable[[], str] | None:
    """The token for the database credential: its account, or its AppRole; None without either."""
    login = _kubernetes(cfg)
    if login is None and cfg.VAULT_APPROLE_DIR:
        login = approle_login(cfg.VAULT_ADDR, Path(cfg.VAULT_APPROLE_DIR))
    return Renewing(login) if login is not None else None
