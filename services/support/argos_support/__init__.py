"""ARG-088 · the diagnostic package the operator reviews before it leaves (F09-11).

Support without remote access: the appliance does not open a door to the supplier; the operator
generates a package, reads it, and sends it through their own channel. The rule of the package is
that **what is reviewed is what leaves**:

- `collect` gathers versions, health, events, the tail of the service logs, the tail of the journal
  (sequence, actor, action and date; never the payload) and the names of the configuration and
  of the secrets (never their values). Nothing from the business database. Every free text passes
  through the same scrubber (`argos_support.scrub`).
- The preview is the files plus an index (`INDEX.json`) with the size and SHA-256 of each file and
  a note for the operator in Spanish.
- `build_package` encrypts only when the index the operator approved is the index of the preview,
  and the files still match it: a file changed afterwards stops the package. The encryption is
  `age` (pyrage) to the public key of support (ADR-0014, point 6).

The same input gives the same files, index and archive: order and timestamps are fixed.
"""

import datetime as dt
import gzip
import hashlib
import io
import json
import re
import shutil
import tarfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import pyrage

from argos_common.errors import ArgosError

from .scrub import Scrubber, secret_values

INDEX = "INDEX.json"
LOG_LINES = 500
JOURNAL_ENTRIES = 200
FORMAT = 1
NOTE = (
    "Paquete de diagnóstico de ARGOS para el soporte. Lea cada fichero antes de enviarlo: lo que "
    "ve en la vista previa es exactamente lo que sale, y sale cifrado para la clave del soporte. "
    "No contiene nada de la base de datos de negocio. Los registros y todo texto libre han pasado "
    "por el depurador de datos personales y de secretos; los secretos aparecen solo por su nombre. "
    "El operador decide si lo envía y por qué canal."
)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


class DiagnosticsError(ArgosError):
    """The package cannot be built as asked: it would not be what the operator reviewed."""


@dataclass(frozen=True, slots=True)
class ServiceState:
    """What the orchestrator says of one service. `env` values only feed the scrubber."""

    name: str
    image: str
    health: str
    health_output: str = ""
    env: Mapping[str, str] = field(default_factory=dict)
    mounts: tuple[str, ...] = ()


class Inspector(Protocol):
    """Read-only view of the orchestrator. It cannot deploy anything, unlike the updater's port."""

    def services(self) -> list[str]: ...
    def state(self, service: str) -> ServiceState: ...
    def logs(self, service: str, lines: int) -> str: ...
    def events(self) -> list[str]: ...


JournalTail = Callable[[int], Sequence[Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class Preview:
    """The files of the package and their index, exactly as they will be encrypted."""

    files: Mapping[str, bytes]
    index: bytes
    generated_at: dt.datetime

    @property
    def index_sha256(self) -> str:
        return hashlib.sha256(self.index).hexdigest()


def _iso(at: dt.datetime) -> str:
    return at.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _index(files: Mapping[str, bytes], scrubbed: Mapping[str, int], at: dt.datetime) -> bytes:
    entries = [
        {
            "name": name,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "scrubbed": scrubbed.get(name, 0),
        }
        for name, data in sorted(files.items())
    ]
    document = {"format": FORMAT, "generated_at": _iso(at), "note": NOTE, "files": entries}
    return _json(document).encode("utf-8")


def collect(
    inspector: Inspector,
    journal_tail: JournalTail,
    installed_version: str | None,
    generated_at: dt.datetime,
) -> Preview:
    """Gather, scrub and index. Nothing is encrypted yet: this is what the operator reads."""
    names = sorted(inspector.services())
    states = [inspector.state(name) for name in names]
    scrub = Scrubber(value for state in states for value in secret_values(state.env))
    files: dict[str, bytes] = {}
    scrubbed: dict[str, int] = {}

    def add(name: str, text: str) -> None:
        clean, count = scrub(text)
        files[name], scrubbed[name] = clean.encode("utf-8"), count

    def add_json(name: str, value: Any) -> None:
        clean, count = scrub.tree(value)
        files[name], scrubbed[name] = _json(clean).encode("utf-8"), count

    versions = [f"installed {installed_version or 'unknown'}"]
    versions += [f"{state.name} {state.image}" for state in states]
    add("versions.txt", "\n".join(versions) + "\n")
    add_json(
        "health.json",
        {state.name: {"status": state.health, "output": state.health_output} for state in states},
    )
    add("events.txt", "".join(f"{line}\n" for line in inspector.events()))
    rows = sorted(journal_tail(JOURNAL_ENTRIES), key=lambda row: int(row["seq"]))
    add_json(
        "journal-tail.json",
        [
            {"seq": int(r["seq"]), "actor": str(r["actor"]), "action": str(r["action"]),
             "at": str(r["at"])}
            for r in rows[-JOURNAL_ENTRIES:]
        ],
    )  # fmt: skip
    names_only = [f"{s.name} {variable}" for s in states for variable in sorted(s.env)]
    names_only += [f"{s.name} {mount}" for s in states for mount in sorted(s.mounts)]
    add("config-names.txt", "".join(f"{line}\n" for line in names_only))
    for state in states:
        clean, count = scrub(inspector.logs(state.name, LOG_LINES))
        name = f"logs/{_SAFE_NAME.sub('_', state.name)}.log"
        files[name] = f"# scrubbed: {count}\n{clean}".encode()
        scrubbed[name] = count
    return Preview(files, _index(files, scrubbed, generated_at), generated_at)


def _check(preview: Preview) -> None:
    """The files are exactly the ones of the index, byte for byte, and nothing else."""
    try:
        listed = {e["name"]: e for e in json.loads(preview.index)["files"]}
    except (ValueError, KeyError, TypeError) as broken:
        raise DiagnosticsError(f"the index cannot be read: {broken}") from None
    if set(listed) != set(preview.files):
        raise DiagnosticsError("the files of the package are not the ones of its index")
    for name, data in preview.files.items():
        if listed[name]["sha256"] != hashlib.sha256(data).hexdigest():
            raise DiagnosticsError(f"{name} changed after the index was generated")


def archive(preview: Preview) -> bytes:
    """A gzipped tar with the index first, sorted, and every timestamp fixed."""
    moment = int(preview.generated_at.timestamp())
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data in [(INDEX, preview.index), *sorted(preview.files.items())]:
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), moment, 0o644
            tar.addfile(info, io.BytesIO(data))
    packed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=packed, mtime=0) as zipped:
        zipped.write(raw.getvalue())
    return packed.getvalue()


def build_package(preview: Preview, approved_index_sha256: str, recipient: str) -> bytes:
    """The package encrypted for support, only for the index the operator approved."""
    if approved_index_sha256 != preview.index_sha256:
        raise DiagnosticsError("the approved index is not the index of this preview")
    _check(preview)
    try:
        key = pyrage.x25519.Recipient.from_str(recipient.strip())
    except Exception as wrong:  # pyrage raises its own error types
        raise DiagnosticsError(f"the support key is not an age recipient: {wrong}") from None
    return bytes(pyrage.encrypt(archive(preview), [key]))


def open_package(package: bytes, identity: str) -> dict[str, bytes]:
    """What support does on arrival: decrypt and read every file (tests and support tooling)."""
    plain = pyrage.decrypt(package, [pyrage.x25519.Identity.from_str(identity.strip())])
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(plain)), mode="r") as tar:
        for member in tar.getmembers():
            extracted = tar.extractfile(member)
            if extracted is not None:
                files[member.name] = extracted.read()
    return files


Status = Literal["collecting", "ready", "unknown"]


class DiagnosticsStore:
    """The folder the API and the collector share: requests in `queue/`, previews in `previews/`.

    The API only writes requests and reads previews; the collector, next to the orchestrator,
    writes the previews. A preview edited on disk no longer matches its index and is refused.
    """

    IDENT = re.compile(r"^[0-9]{10}-[0-9a-f]{8}$")

    def __init__(self, root: Path) -> None:
        self.queue = root / "queue"
        self.previews = root / "previews"

    def _checked(self, ident: str) -> str:
        if not self.IDENT.fullmatch(ident):
            raise DiagnosticsError(f"{ident!r} is not an identifier of a diagnostic package")
        return ident

    def request(self, requested_by: str, now: dt.datetime | None = None) -> str:
        moment = now or dt.datetime.now(dt.UTC)
        ident = f"{int(moment.timestamp()):010d}-{uuid.uuid4().hex[:8]}"
        self.queue.mkdir(parents=True, exist_ok=True)
        temporary = self.queue / f".{ident}.tmp"
        temporary.write_text(json.dumps({"requested_by": requested_by}), encoding="utf-8")
        temporary.replace(self.queue / f"{ident}.json")
        return ident

    def pending(self) -> list[str]:
        if not self.queue.is_dir():
            return []
        found = (path.stem for path in self.queue.glob("*.json"))
        return sorted(ident for ident in found if self.IDENT.fullmatch(ident))

    def status(self, ident: str) -> Status:
        ident = self._checked(ident)
        if (self.previews / ident / INDEX).is_file():
            return "ready"
        if (self.queue / f"{ident}.json").is_file():
            return "collecting"
        return "unknown"

    def save(self, ident: str, preview: Preview) -> None:
        ident = self._checked(ident)
        temporary = self.previews / f".{ident}.tmp"
        shutil.rmtree(temporary, ignore_errors=True)
        for name, data in {**preview.files, INDEX: preview.index}.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        temporary.replace(self.previews / ident)
        (self.queue / f"{ident}.json").unlink(missing_ok=True)

    def load(self, ident: str) -> Preview:
        folder = self.previews / self._checked(ident)
        if not (folder / INDEX).is_file():
            raise DiagnosticsError(f"the preview {ident} is not ready")
        index = (folder / INDEX).read_bytes()
        files = {
            path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*"))
            if path.is_file() and path.name != INDEX
        }
        try:
            at = dt.datetime.strptime(json.loads(index)["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, KeyError, TypeError) as broken:
            raise DiagnosticsError(f"the index of {ident} cannot be read: {broken}") from None
        preview = Preview(files, index, at.replace(tzinfo=dt.UTC))
        _check(preview)
        return preview


__all__ = [
    "DiagnosticsError",
    "DiagnosticsStore",
    "Inspector",
    "JournalTail",
    "Preview",
    "ServiceState",
    "archive",
    "build_package",
    "collect",
    "open_package",
]
