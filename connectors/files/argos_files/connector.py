"""File connector: metadata first, content only as the first block of a sample (ARG-017)."""

import fnmatch
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from argos_connector.base import Connector
from argos_connector.probes import ProbeSpec
from argos_connector.tls import require_tls

from .backends import FileBackend, normalise_prefix
from .backends.local import LocalBackend

MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "zip/ooxml"),
    (b"\x89PNG", "png"),
    (b"\xff\xd8\xff", "jpeg"),
)
HEAD_BYTES = 4096
YEAR_S = 31_557_600
_VERBS = {"scan_schema": "WALK", "count": "WALK", "sample": "READ_HEAD", "check_config": "GET_ACL"}


def sniff(head: bytes) -> str:
    if head[128:132] == b"DICM":  # the DICOM preamble puts its magic at offset 128
        return "dicom"
    for signature, name in MAGIC:
        if head.startswith(signature):
            return name
    return "unknown"


class FilesConnector(Connector):
    kind = "files"

    def __init__(
        self,
        *args: Any,
        backend: FileBackend | None = None,
        now: Callable[[], float] = time.time,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._backend = backend
        self._now = now

    @property
    def backend(self) -> FileBackend:
        if self._backend is None:
            raise RuntimeError("connector is not open: call open() first")
        return self._backend

    @property
    def max_walk_entries(self) -> int:
        return int(self.config.get("max_walk_entries", 1_000_000))

    def open(self) -> None:
        if self._backend is not None:
            return
        protocol = self.config.get("protocol")
        # The first block of each file crosses the network before it is hashed.
        insecure = self.config.get("allow_insecure") is True
        if protocol == "smb":
            from .backends.smb import SmbBackend

            # SMB 3 encryption is demanded; a declared exception leaves it to negotiation.
            self._backend = SmbBackend(self.context.credentials, encrypt=None if insecure else True)
        elif protocol == "s3":
            from .backends.s3 import S3Backend

            endpoint = str(self.context.credentials.get("endpoint_url") or "https://")
            require_tls(endpoint.lower().startswith("https://"), self.config, endpoint)
            self._backend = S3Backend(self.context.credentials)
        elif protocol == "local":
            self._backend = LocalBackend(self.config["mount"])
        else:
            raise ValueError(f"unknown file protocol: {protocol!r}")

    def close(self) -> None:
        backend, self._backend = self._backend, None
        release = getattr(backend, "close", None)
        if callable(release):
            release()  # remote backends hold pooled sessions until the interpreter exits

    def render(self, spec: ProbeSpec) -> ProbeSpec:
        verb = _VERBS.get(spec.kind)
        if verb is None:
            return spec  # validate() reports the unknown kind
        prefix = normalise_prefix(spec.target)
        limit = {
            "scan_schema": self.max_walk_entries,
            "count": self.max_walk_entries,
            "sample": self._sample_size(spec),
            "check_config": 1,
        }[spec.kind]
        glob = spec.params.get("glob") if spec.kind == "count" else None
        pattern = f" glob={glob}" if glob is not None else ""
        return replace(spec, target=prefix, statement=f"{verb} /{prefix} limit={limit}{pattern}")

    def _sample_size(self, spec: ProbeSpec) -> int:
        return min(int(spec.params.get("k", 50)), self.context.budget.max_rows_per_probe)

    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        total, size = 0, 0
        by_ext: dict[str, int] = {}
        age_years: dict[str, int] = {}
        now = self._now()
        for entry in self.backend.walk(spec.target, self.max_walk_entries):
            total += 1
            size += entry.size
            name = entry.path.rsplit("/", 1)[-1]
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else "(none)"
            by_ext[ext] = by_ext.get(ext, 0) + 1
            years = str(max(0, int((now - entry.mtime) // YEAR_S)))
            age_years[years] = age_years.get(years, 0) + 1
        summary = {
            "total": total,
            "bytes": size,
            "by_ext": by_ext,
            "age_years": age_years,
            "capped": total >= self.max_walk_entries,
        }
        return summary, total

    def _do_count(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        pattern = str(spec.params.get("glob", "*"))
        older = spec.params.get("older_than_years")
        now = self._now()
        walked = matched = 0
        for entry in self.backend.walk(spec.target, self.max_walk_entries):
            walked += 1
            if not fnmatch.fnmatchcase(entry.path.rsplit("/", 1)[-1], pattern):
                continue
            if older is not None and now - entry.mtime < float(older) * YEAR_S:
                continue
            matched += 1
        data = {
            "count": matched,
            "glob": pattern,
            "older_than_years": older,
            "capped": walked >= self.max_walk_entries,
        }
        return data, matched

    def _do_sample(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        hasher = self.context.hasher
        entries = []
        for entry in self.backend.walk(spec.target, self._sample_size(spec)):
            head = self.backend.read_head(entry.path, HEAD_BYTES)
            entries.append(
                {
                    "path_digest": hasher.digest(entry.path),
                    "type": sniff(head),
                    "size": entry.size,
                    "head_digest": hasher.digest(head),
                }
            )
        return {"n": len(entries), "entries": entries}, len(entries)

    def _do_check_config(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        return {"target": spec.target, "acl": self.backend.get_acl(spec.target)}, 1
