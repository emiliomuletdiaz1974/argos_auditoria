"""ARG-089 · what the backup and its restore test share (F09-12).

- `Restic`: restic in an image pinned by digest (ADR-0014, point 6). The password of the repository
  goes in a file mounted read-only for the one command, never in an argument or a variable: it
  does not show in `docker inspect` nor in any log. The file is deleted when the block ends.
- `Vault`: the password of restic (`argos/platform/backup`) and a dynamic database credential of
  the read-only role `svc_backup` (F09-05), revoked when the run ends.
- `docker`: fixed argument lists, never a shell.
"""

import datetime as dt
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self

RESTIC_IMAGE = (
    "restic/restic:0.18.1@sha256:39d9072fb5651c80d75c7a811612eb60b4c06b32ffe87c2e9f3c7222e1797e76"
)
PASSWORD_PATH = "/run/secrets/restic"  # noqa: S105 - where the file is mounted, not a password
RETENTION = ("--keep-daily", "14", "--keep-weekly", "8", "--keep-monthly", "12")
CHECK_SUBSET = "5%"
ACTOR = "system:backup"
# A repository written as `s3:…`, `sftp:…` or `rest:…` is remote; anything else is a local folder.
_REMOTE = re.compile(r"^(s3|sftp|rest|b2|azure|gs|swift|rclone):")


class Runner(Protocol):
    def __call__(self, args: Sequence[str], stdin: bytes | None = None) -> bytes: ...


def docker(args: Sequence[str], stdin: bytes | None = None) -> bytes:
    """Run a fixed command; a failure carries the end of what the command said."""
    done = subprocess.run(  # noqa: S603 - fixed argument lists, no shell
        list(args), input=stdin, capture_output=True, check=False, timeout=3600
    )
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", errors="replace").strip()[-600:]
        raise RuntimeError(f"{args[0]} {args[1] if len(args) > 1 else ''} failed: {said}")
    return done.stdout


@dataclass(frozen=True, slots=True)
class Snapshot:
    id: str
    time: dt.datetime
    tag: str


class Restic:
    """`with Restic(...) as restic:` — the password file lives exactly as long as the block."""

    def __init__(
        self,
        run: Runner,
        repository: str,
        password: str,
        scratch: Path | None = None,
        image: str = RESTIC_IMAGE,
    ) -> None:
        self._run = run
        self._remote = bool(_REMOTE.match(repository))
        self._repository = repository
        self._password = password
        self._scratch = scratch
        self._image = image
        self._folder: Path | None = None

    def __enter__(self) -> Self:
        self._folder = Path(tempfile.mkdtemp(prefix="restic-", dir=self._scratch))
        (self._folder / "password").write_text(self._password, encoding="utf-8")
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._folder is not None:
            shutil.rmtree(self._folder, ignore_errors=True)
            self._folder = None

    def run(
        self,
        args: Sequence[str],
        mounts: Sequence[tuple[str, str, bool]] = (),
        network: str | None = None,
    ) -> bytes:
        if self._folder is None:
            raise RuntimeError("restic is used inside its `with` block")
        repository = self._repository if self._remote else "/repo"
        command = [
            "docker", "run", "--rm",
            "--network", network or ("bridge" if self._remote else "none"),
            "-e", f"RESTIC_PASSWORD_FILE={PASSWORD_PATH}",
            "-e", f"RESTIC_REPOSITORY={repository}",
            "-v", f"{self._folder / 'password'}:{PASSWORD_PATH}:ro",
        ]  # fmt: skip
        if not self._remote:
            Path(self._repository).mkdir(parents=True, exist_ok=True)
            command += ["-v", f"{Path(self._repository).resolve()}:/repo"]
        for source, target, read_only in mounts:
            command += ["-v", f"{source}:{target}{':ro' if read_only else ''}"]
        return self._run([*command, self._image, *args])

    def ensure(self) -> None:
        """The repository, created the first time."""
        exists = (Path(self._repository) / "config").is_file() if not self._remote else True
        if self._remote:
            try:
                self.run(["cat", "config"])
            except RuntimeError:
                exists = False
        if not exists:
            self.run(["init"])

    def backup(
        self, paths: Sequence[str], tag: str, mounts: Sequence[tuple[str, str, bool]]
    ) -> str:
        """One set with its tag; returns the id of the snapshot."""
        out = self.run(["backup", "--json", "--host", "argos", "--tag", tag, *paths], mounts)
        for line in reversed(out.decode("utf-8").splitlines()):
            message = json.loads(line) if line.startswith("{") else {}
            if message.get("message_type") == "summary":
                return str(message["snapshot_id"])
        raise RuntimeError(f"restic did not report the snapshot of {tag}")

    def forget_and_check(self) -> None:
        """14 daily, 8 weekly and 12 monthly copies; then a rotating read of 5 % of the data."""
        self.run(["forget", "--prune", *RETENTION])
        self.run(["check", f"--read-data-subset={CHECK_SUBSET}"])

    def latest(self, tag: str) -> Snapshot:
        found: list[dict[str, Any]] = json.loads(
            self.run(["snapshots", "--json", "--tag", tag, "--latest", "1"]) or b"[]"
        )
        if not found:
            raise RuntimeError(f"there is no copy with the tag {tag}")
        last = max(found, key=lambda s: str(s["time"]))
        return Snapshot(str(last["id"]), _time(str(last["time"])), tag)

    def restore(self, snapshot: str, target: Path, include: Sequence[str] = ()) -> None:
        """The snapshot into `target` (a host folder), all of it or only what `include` names."""
        args = ["restore", snapshot, "--target", "/target"]
        for path in include:
            args += ["--include", path]
        self.run(args, [(str(target), "/target", False)])


def _time(text: str) -> dt.datetime:
    """restic writes nanoseconds; Python keeps microseconds."""
    trimmed = re.sub(r"(\.\d{6})\d+", r"\1", text)
    return dt.datetime.fromisoformat(trimmed.replace("Z", "+00:00"))


class Vault:
    """The two things the backup asks Vault for. Development: root token; appliance: AppRole."""

    def __init__(self, address: str, token: str) -> None:
        self._address = address.rstrip("/")
        self._token = token

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(  # noqa: S310 - the Vault of the appliance
            f"{self._address}/v1/{path}",
            method=method,
            headers={"X-Vault-Token": self._token},
            data=json.dumps(body).encode() if body is not None else None,
        )
        with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310
            raw = answer.read()
        return json.loads(raw) if raw else {}

    def restic_password(self) -> str:
        return str(
            self._call("GET", "argos/data/platform/backup")["data"]["data"]["restic_password"]
        )

    def database_credential(self, role: str = "svc-backup") -> tuple[str, str, str]:
        """(user, password, lease): an ephemeral login user of `svc_backup`."""
        answer = self._call("GET", f"db/creds/{role}")
        return str(answer["data"]["username"]), str(answer["data"]["password"]), answer["lease_id"]

    def revoke(self, lease: str) -> None:
        self._call("PUT", "sys/leases/revoke", {"lease_id": lease})

    def kv_tree(self, prefix: str = "") -> dict[str, Any]:
        """Every secret under `argos/`, for the configuration set (encrypted by restic)."""
        tree: dict[str, Any] = {}
        for key in self._call("LIST", f"argos/metadata/{prefix}")["data"]["keys"]:
            if key.endswith("/"):
                tree.update(self.kv_tree(prefix + key))
            else:
                tree[prefix + key] = self._call("GET", f"argos/data/{prefix}{key}")["data"]["data"]
        return tree


def database_url(
    user: str, password: str, host: str, port: int, database: str = "argos", ca: str | None = None
) -> str:
    """Verified TLS, as every other client of PostgreSQL (F09-06): the internal CA of
    `ARGOS_TLS_DIR` and the name or address of the server checked against its certificate."""
    from urllib.parse import quote

    authority = ca or str(Path(os.environ.get("ARGOS_TLS_DIR", "/run/tls")) / "ca.crt")
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{database}"
        f"?sslmode=verify-full&sslrootcert={quote(authority, safe='/:')}"
    )


def random_password() -> str:
    return secrets.token_urlsafe(24)
