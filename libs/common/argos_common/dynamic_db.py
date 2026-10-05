"""ARG-085 · dynamic database credentials, renewed in place (F09-05, deviation note ARG-085).

Vault's `database` engine creates, for each service, an ephemeral PostgreSQL user that is a member
of its role (`svc_<service>`) and expires with its lease: a credential stolen today is no good
tomorrow. The process asks for one at start and asks for a new one before it expires.

Where the credential goes: a libpq service file (`pg_service.conf`), written whole and replaced
atomically. The services connect with `postgresql://host:port/argos?service=argos`, so libpq reads
the user and the password from the file on every new connection; nothing that already holds the
connection string has to change, and the connections already open finish with the credential they
opened with. Nothing here writes the user or the password to a log.

The same code runs in two ways: inside the service (`start_from_config`), or as its own process
next to a service that must not reach Vault (`python -m argos_common.dynamic_db`), which writes the
file to a volume the two share. How it signs in to Vault is `vault_auth` (K-06).
"""

import argparse
import logging
import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .config import ArgosConfig
from .vault_auth import database_login, vault_request

logger = logging.getLogger(__name__)

SERVICE_NAME = "argos"
RENEW_BEFORE = 3600.0  # an hour before a long credential expires
RETRY_MIN = 1.0
RETRY_MAX = 60.0
EXPIRED_RETRY = 5.0


@dataclass(frozen=True, slots=True)
class Lease:
    username: str = field(repr=False)
    password: str = field(repr=False)
    ttl: float

    def __post_init__(self) -> None:
        for value in (self.username, self.password):
            if not value or any(c in value for c in "\r\n\0"):
                raise ValueError("the lease would not fit in a libpq service file")
        if self.ttl <= 0:
            raise ValueError("the lease has no time left")


class CredentialSource(Protocol):
    def issue(self) -> Lease: ...


def renewal_delay(ttl: float) -> float:
    """An hour before a long credential expires, or at half the life of a short one."""
    return ttl - RENEW_BEFORE if ttl >= 2 * RENEW_BEFORE else ttl / 2


@dataclass(frozen=True, slots=True)
class VaultDatabaseSource:
    """Credentials of one role of the `db/` engine."""

    addr: str
    role: str
    token: Callable[[], str] = field(repr=False)

    def issue(self) -> Lease:
        answer = vault_request(self.addr, f"db/creds/{self.role}", self.token())
        data = answer["data"]
        return Lease(str(data["username"]), str(data["password"]), float(answer["lease_duration"]))


def service_file_text(lease: Lease, service: str = SERVICE_NAME) -> str:
    return f"[{service}]\nuser={lease.username}\npassword={lease.password}\n"


def parse_service_file(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
        elif "=" in line and current is not None:
            key, _, value = line.partition("=")
            current[key] = value
    return sections


class DynamicCredentials:
    """Keeps a valid credential in the service file for as long as the process lives."""

    def __init__(
        self,
        source: CredentialSource,
        service_file: Path,
        service: str = SERVICE_NAME,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self.service_file = service_file
        self._service = service
        self._clock = clock
        self._expires_at = 0.0

    def _write(self, lease: Lease) -> None:
        folder = self.service_file.parent
        folder.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=folder, prefix=".pg_service.")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as out:
                out.write(service_file_text(lease, self._service))
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.service_file)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def refresh(self) -> float:
        """Ask for a new credential and put it in place; the wait until the next renewal."""
        lease = self._source.issue()
        self._write(lease)
        self._expires_at = self._clock() + lease.ttl
        logger.info("database credential renewed", extra={"ttl_seconds": int(lease.ttl)})
        return renewal_delay(lease.ttl)

    def start_blocking(self) -> None:
        """The first credential: without it the service does not start."""
        self.refresh()

    def step(self) -> float:
        """One renewal; a failure keeps the current credential and says when to try again."""
        try:
            return self.refresh()
        except Exception as exc:  # noqa: BLE001 - any failure: keep serving and try again
            left = self._expires_at - self._clock()
            logger.error(
                "database credential not renewed",
                extra={"error": type(exc).__name__, "seconds_left": int(max(left, 0))},
            )
            if left <= 0:
                return EXPIRED_RETRY
            return min(RETRY_MAX, max(RETRY_MIN, left / 10))

    def run(self, stop: threading.Event, first_wait: float) -> None:
        wait = first_wait
        while not stop.wait(wait):
            wait = self.step()

    def start(self) -> threading.Event:
        """The first credential now, the renewals in a background thread."""
        first_wait = self.refresh()
        stop = threading.Event()
        threading.Thread(
            target=self.run, args=(stop, first_wait), name="db-credentials", daemon=True
        ).start()
        return stop


def from_config(cfg: ArgosConfig) -> DynamicCredentials | None:
    """The renewal this service is configured for, or None when it uses a fixed credential."""
    if not cfg.DATABASE_VAULT_ROLE:
        return None
    login = database_login(cfg)
    if login is None:
        raise ValueError("DATABASE_VAULT_ROLE needs VAULT_KUBERNETES_ROLE or VAULT_APPROLE_DIR")
    source = VaultDatabaseSource(cfg.VAULT_ADDR, cfg.DATABASE_VAULT_ROLE, login)
    return DynamicCredentials(source, Path(cfg.DATABASE_SERVICE_FILE))


def start_from_config(cfg: ArgosConfig) -> threading.Event | None:
    """Called first thing by every service entry point, before any connection."""
    credentials = from_config(cfg)
    if credentials is None:
        return None
    os.environ["PGSERVICEFILE"] = str(credentials.service_file)
    return credentials.start()


def main(argv: list[str] | None = None) -> int:
    """The renewal as a process of its own, for a service that must not reach Vault."""
    from .config import get_config

    parser = argparse.ArgumentParser(description="keep a dynamic database credential in a file")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    credentials = from_config(get_config())
    if credentials is None:
        print("ARGOS_DATABASE_VAULT_ROLE is not set", file=sys.stderr)
        return 2
    credentials.run(threading.Event(), credentials.refresh())
    return 0


if __name__ == "__main__":
    sys.exit(main())
