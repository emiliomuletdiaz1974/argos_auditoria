"""File backends expose only walk, read_head and get_acl: nothing that changes a file (ARG-017)."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from argos_common.errors import ReadOnlyViolationError


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str  # relative, "/"-separated
    size: int
    mtime: float


@dataclass(frozen=True, slots=True)
class WalkIncomplete:
    """Yielded by a walk that could not see everything: a limit reached before the end, a folder
    it could not read, a file that vanished. The count that follows says it is capped (QA-016)."""

    reason: str


class FileBackend(Protocol):
    def walk(self, prefix: str, limit: int) -> Iterator[FileEntry | WalkIncomplete]: ...

    def read_head(self, path: str, nbytes: int) -> bytes: ...

    def get_acl(self, path: str) -> dict[str, Any]: ...


def normalise_prefix(prefix: str) -> str:
    parts = [p for p in prefix.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ReadOnlyViolationError(f"path escapes the share root: {prefix!r}")
    return "/".join(parts)
