"""ARG-090 · the airlock of the isolated appliance (F09-13).

The appliance has no way out to the Internet (P-02). What comes in and what goes out crosses one
formal door, on removable media:

- **In** (`Gate.scan`): update bundles (ARG-086), normative content bundles (ARG-040) and time
  stamp replies (`.tsr`, ARG-065). The medium is read-only. Each file is recognised only by the
  pattern of its kind, refused if it is not a regular file (links, folders, devices are never
  read) or larger than its kind allows, copied to a work zone while its SHA-256 is computed, and
  handed to the importer of its kind, which verifies **its own** signature before applying
  anything. The work zone is emptied after every file.
- **Out** (`Gate.export`): time stamp queries (`.tsq`), the diagnostic package (ARG-088), dossiers
  and credentials. That list is a constant, `EXPORT_KINDS`: any other kind is a `PermissionError`,
  and a gate cannot even be built with an exporter outside it.

Every file and every export, accepted or not, goes to the journal and to the security log with
who asked, the file, its hash and the result.
"""

import datetime as dt
import hashlib
import re
import shutil
import stat
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The closed list of what may leave the appliance. A constant on purpose: not configuration.
EXPORT_KINDS: frozenset[str] = frozenset({"tsq", "diagnostics", "dossier", "credential"})


@dataclass(frozen=True, slots=True)
class ImportRule:
    pattern: re.Pattern[str]
    max_bytes: int
    sidecar: str | None = None  # a second file that travels with it (the signature of content)


IMPORT_RULES: Mapping[str, ImportRule] = {
    "update": ImportRule(
        re.compile(r"argos-update-[0-9A-Za-z][0-9A-Za-z.+-]{0,63}\.tar"), 16 << 30
    ),
    "content": ImportRule(
        re.compile(r"argos-ontology-[0-9A-Za-z][0-9A-Za-z.+-]{0,63}\.tar\.gz"), 256 << 20, ".sig"
    ),
    "tsr": ImportRule(re.compile(r"[0-9a-f]{32}\.tsr"), 64 << 10),
}
SIDECAR_MAX_BYTES = 64 << 10
CHUNK = 1 << 20

Importer = Callable[[Path, str], str]  # (file in the work zone, actor) -> what was done
Exporter = Callable[[Path, Mapping[str, str]], None]  # (empty folder, parameters)
Recorder = Callable[[str, str, dict[str, Any], str], None]  # actor, action, detail, outcome


class GateError(Exception):
    """A file the airlock refuses before any importer sees it."""


@dataclass(frozen=True, slots=True)
class Imported:
    file: str
    kind: str | None
    result: str  # "imported" | "rejected"
    reason: str
    sha256: str | None = None
    size: int | None = None


@dataclass(frozen=True, slots=True)
class Exported:
    id: str
    kind: str
    files: list[dict[str, Any]] = field(default_factory=list)


def check_name(name: str) -> str | None:
    """The kind a file name belongs to, or `None`: only whole-name matches of the patterns."""
    for kind, rule in IMPORT_RULES.items():
        if rule.pattern.fullmatch(name):
            return kind
    return None


def _regular(path: Path) -> int:
    """The size of a regular file, looked at without following links; anything else is refused."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise GateError("not a regular file (a link, a folder or a device is never read)")
    return info.st_size


def _copy(source: Path, target: Path, limit: int) -> str:
    """Copy while hashing, and stop if the file grows past its limit while being read."""
    digest, copied = hashlib.sha256(), 0
    with source.open("rb") as read, target.open("xb") as write:
        while chunk := read.read(CHUNK):
            copied += len(chunk)
            if copied > limit:
                raise GateError(f"larger than the {limit} bytes its kind allows")
            digest.update(chunk)
            write.write(chunk)
    return digest.hexdigest()


class Gate:
    def __init__(
        self,
        inbox: Path,
        outbox: Path,
        work: Path,
        importers: Mapping[str, Importer],
        exporters: Mapping[str, Exporter],
        record: Recorder,
    ) -> None:
        outside = set(exporters) - EXPORT_KINDS
        if outside:
            raise ValueError(f"exporters outside the closed list: {sorted(outside)}")
        unknown = set(importers) - set(IMPORT_RULES)
        if unknown:
            raise ValueError(f"importers of kinds the airlock does not know: {sorted(unknown)}")
        self.inbox, self.outbox, self.work = inbox, outbox, work
        self._importers = dict(importers)
        self._exporters = dict(exporters)
        self.record = record

    # ------------------------------------------------------------------ in

    def scan(self, actor: str) -> list[Imported]:
        """Every entry of the medium, in order; each one ends imported or rejected, and recorded."""
        sidecars = {
            path.name + rule.sidecar
            for kind, rule in IMPORT_RULES.items()
            if rule.sidecar
            for path in self.inbox.iterdir()
            if rule.pattern.fullmatch(path.name)
        }
        results = []
        for entry in sorted(self.inbox.iterdir(), key=lambda p: p.name):
            if entry.name in sidecars:
                continue  # it travels with its file
            result = self._import(entry, actor)
            detail = {
                "file": result.file[:200],
                "kind": result.kind or "",
                "sha256": result.sha256 or "",
                "size": result.size or 0,
                "result": result.result,
                "reason": result.reason[:200],
            }
            outcome = "succeeded" if result.result == "imported" else "refused"
            self.record(actor, "airgap.import", detail, outcome)
            results.append(result)
        return results

    def _import(self, entry: Path, actor: str) -> Imported:
        kind = check_name(entry.name)
        if kind is None:
            return Imported(entry.name, None, "rejected", "not a kind the airlock imports")
        rule = IMPORT_RULES[kind]
        zone = self.work / uuid.uuid4().hex
        sha256 = size = None
        try:
            size = _regular(entry)  # before anything else: a link is never followed
            importer = self._importers.get(kind)
            if importer is None:
                raise GateError(f"no importer for {kind} here")
            if size > rule.max_bytes:
                raise GateError(f"larger than the {rule.max_bytes} bytes its kind allows")
            zone.mkdir(parents=True)
            copy = zone / entry.name
            sha256 = _copy(entry, copy, rule.max_bytes)
            if rule.sidecar:
                sidecar = entry.with_name(entry.name + rule.sidecar)
                if not sidecar.exists():
                    raise GateError(f"{sidecar.name} does not travel with it")
                _regular(sidecar)
                _copy(sidecar, zone / sidecar.name, SIDECAR_MAX_BYTES)
            done = importer(copy, actor)
        except Exception as refused:  # noqa: BLE001 - every refusal is a result, recorded
            return Imported(entry.name, kind, "rejected", str(refused)[:500], sha256, size)
        finally:
            shutil.rmtree(zone, ignore_errors=True)
        return Imported(entry.name, kind, "imported", done, sha256, size)

    # ------------------------------------------------------------------ out

    def export(self, kind: str, actor: str, params: Mapping[str, str]) -> Exported:
        """One export of a kind of the closed list into a new folder of the medium."""
        if kind not in EXPORT_KINDS:
            self.record(actor, "airgap.export", {"kind": kind[:60]}, "refused")
            raise PermissionError(f"{kind!r} is not in the closed list of exports")
        exporter = self._exporters.get(kind)
        if exporter is None:
            raise PermissionError(f"no exporter for {kind} is available here")
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        ident = f"{stamp}-{kind}-{uuid.uuid4().hex[:8]}"
        folder = self.outbox / ident
        folder.mkdir(parents=True)
        try:
            exporter(folder, params)
        except Exception as failed:
            shutil.rmtree(folder, ignore_errors=True)
            failure = {"kind": kind, "reason": str(failed)[:200]}
            self.record(actor, "airgap.export", failure, "failed")
            raise
        files = [
            {
                "name": path.relative_to(folder).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(folder.rglob("*"))
            if path.is_file()
        ]
        # The record keeps how many files and the hash of their list; the answer lists them.
        listing = "\n".join(f"{f['sha256']}  {f['name']}" for f in files)
        detail: dict[str, Any] = {
            "kind": kind,
            "id": ident,
            "files": len(files),
            "sha256": hashlib.sha256(listing.encode()).hexdigest(),
            **{k: str(v)[:100] for k, v in params.items() if k != "approved_index_sha256"},
        }
        self.record(actor, "airgap.export", detail, "succeeded")
        return Exported(ident, kind, files)


def recorder(dsn: str) -> Recorder:
    """Every file and every export: to the journal (what the appliance did) and to the security
    log (who brought or took what)."""
    from argos_common import security_log
    from argos_common.journal_pg import PostgresJournal

    def record(actor: str, action: str, detail: dict[str, Any], outcome: str) -> None:
        PostgresJournal(dsn).append(actor, action, {**detail, "outcome": outcome})
        log = security_log.log(dsn)
        log.record(action, actor, outcome, detail, source="argos-airgap")

    return record


__all__ = [
    "EXPORT_KINDS",
    "IMPORT_RULES",
    "Exported",
    "Gate",
    "GateError",
    "ImportRule",
    "Imported",
    "check_name",
    "recorder",
]
