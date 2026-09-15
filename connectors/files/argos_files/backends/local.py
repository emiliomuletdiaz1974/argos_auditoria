"""Local backend: an NFS or SMB share mounted into the connector's pod (ARG-017)."""

import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from argos_common.errors import ReadOnlyViolationError

from . import FileEntry, normalise_prefix


class LocalBackend:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve(strict=True)

    def _resolve(self, path: str) -> Path:
        candidate = (self._root / normalise_prefix(path)).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise ReadOnlyViolationError(f"path escapes the share root: {path!r}")
        return candidate

    def walk(self, prefix: str, limit: int) -> Iterator[FileEntry]:
        count = 0
        for directory, subdirectories, files in os.walk(self._resolve(prefix)):
            subdirectories.sort()
            for name in sorted(files):
                full = Path(directory) / name
                info = full.stat()
                relative = full.relative_to(self._root).as_posix()
                yield FileEntry(relative, info.st_size, info.st_mtime)
                count += 1
                if count >= limit:
                    return

    def read_head(self, path: str, nbytes: int) -> bytes:
        with self._resolve(path).open("rb") as handle:
            return handle.read(nbytes)

    def get_acl(self, path: str) -> dict[str, Any]:
        info = self._resolve(path).stat()
        return {"mode": oct(stat.S_IMODE(info.st_mode)), "uid": info.st_uid, "gid": info.st_gid}
