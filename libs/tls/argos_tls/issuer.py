"""ARG-083 · the certificate issuer of the development environment (`cert-issuer`, F09-06).

For each service it asks Vault's internal CA (`pki_int/issue/argos-svc`) for a certificate with
the service's DNS name, 30 days long, and renews it when two thirds of its life have gone (day 20).
Each one goes to the folder of its service (`<root>/<service>/`), which only that service mounts;
the private key never leaves that folder and is written with mode 0600.

On the appliance cert-manager does this job with the same CA (`platform/k8s/security/mtls.yaml`).

    ARGOS_TLS_SERVICES="api=api;postgres=postgres;nats=nats"   folder=names (first one is the CN)
    ARGOS_TLS_ROOT=/certs  VAULT_ADDR=http://vault:8200  VAULT_APPROLE_DIR=/run/secrets/approle
"""

import datetime as dt
import ipaddress
import logging
import os
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from cryptography import x509

from . import CA_FILE, CERT_FILE, KEY_FILE

logger = logging.getLogger(__name__)

ROLE_PATH = "pki_int/issue/argos-svc"
TTL = "720h"
RENEW_AT = 2 / 3  # of the life of the certificate: day 20 of 30
ALWAYS = ("localhost", "127.0.0.1")  # every service answers its own health check through them


@dataclass(frozen=True, slots=True)
class Request:
    folder: str
    names: tuple[str, ...]

    @property
    def common_name(self) -> str:
        return self.names[0]


def parse_services(spec: str) -> list[Request]:
    requests = []
    for item in filter(None, (part.strip() for part in spec.split(";"))):
        folder, _, names = item.partition("=")
        listed = tuple(n.strip() for n in names.split(",") if n.strip())
        if not folder or not listed:
            raise ValueError(f"a service needs a folder and at least one name: {item!r}")
        requests.append(Request(folder.strip(), listed))
    return requests


def due(cert_file: Path, now: dt.datetime) -> bool:
    """Whether the certificate is missing or two thirds of its life have gone."""
    try:
        cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    except (OSError, ValueError):
        return True
    start, end = cert.not_valid_before_utc, cert.not_valid_after_utc
    return now >= start + (end - start) * RENEW_AT


def _write(path: Path, data: str, mode: int) -> None:
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
            out.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class Vault:
    def __init__(self, addr: str, token: Callable[[], str]) -> None:
        self._http = httpx.Client(base_url=f"{addr.rstrip('/')}/v1/", timeout=10)
        self._token = token

    def root(self) -> str:
        """The root CA today: when it changes (a new development Vault), everything is reissued."""
        answer = self._http.get("pki/ca/pem")
        answer.raise_for_status()
        return answer.text.strip()

    def issue(self, request: Request) -> tuple[str, str, str]:
        dns = [n for n in (*request.names, *ALWAYS) if not _is_ip(n)]
        ips = [n for n in (*request.names, *ALWAYS) if _is_ip(n)]
        answer = self._http.post(
            ROLE_PATH,
            headers={"X-Vault-Token": self._token()},
            json={
                "common_name": request.common_name,
                "alt_names": ",".join(dict.fromkeys(dns[1:])),
                "ip_sans": ",".join(dict.fromkeys(ips)),
                "ttl": TTL,
            },
        )
        answer.raise_for_status()
        data = answer.json()["data"]
        chain = [str(c) for c in data.get("ca_chain") or [data["issuing_ca"]]]
        root = self._http.get("pki/ca/pem").text.strip()
        if root and root not in chain:
            chain.append(root)
        leaf = f"{data['certificate']}\n{data['issuing_ca']}\n"
        return leaf, str(data["private_key"]) + "\n", "\n".join(chain) + "\n"


def _is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def approle_token(addr: str, approle_dir: Path) -> Callable[[], str]:
    def login() -> str:
        answer = httpx.post(
            f"{addr.rstrip('/')}/v1/auth/approle/login",
            json={
                "role_id": (approle_dir / "role_id").read_text(encoding="utf-8").strip(),
                "secret_id": (approle_dir / "secret_id").read_text(encoding="utf-8").strip(),
            },
            timeout=10,
        )
        answer.raise_for_status()
        return str(answer.json()["auth"]["client_token"])

    return login


def renew(vault: Vault, root: Path, requests: list[Request], now: dt.datetime) -> list[str]:
    """Issue what is due; the folders renewed."""
    renewed = []
    current_root = vault.root()
    for request in requests:
        folder = root / request.folder
        folder.mkdir(parents=True, exist_ok=True)
        try:
            same_ca = current_root in (folder / CA_FILE).read_text(encoding="utf-8")
        except OSError:
            same_ca = False
        if same_ca and not due(folder / CERT_FILE, now):
            continue
        cert, key, ca = vault.issue(request)
        _write(folder / KEY_FILE, key, 0o600)
        _write(folder / CERT_FILE, cert, 0o644)
        _write(folder / CA_FILE, ca, 0o644)
        renewed.append(request.folder)
        logger.info("certificate issued", extra={"service": request.folder})
    return renewed


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    addr = os.environ.get("VAULT_ADDR", "http://vault:8200")
    vault = Vault(addr, approle_token(addr, Path(os.environ["VAULT_APPROLE_DIR"])))
    requests = parse_services(os.environ["ARGOS_TLS_SERVICES"])
    root = Path(os.environ.get("ARGOS_TLS_ROOT", "/certs"))
    interval = float(os.environ.get("ARGOS_TLS_CHECK_SECONDS", "60"))
    while True:
        try:
            renew(vault, root, requests, dt.datetime.now(dt.UTC))
        except (httpx.HTTPError, OSError, KeyError) as exc:
            logger.error("certificates not renewed", extra={"error": type(exc).__name__})
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
