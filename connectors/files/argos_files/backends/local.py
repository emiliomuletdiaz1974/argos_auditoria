"""Local backend: an NFS or SMB share mounted into the connector's pod (ARG-017)."""

import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from argos_common.errors import ReadOnlyViolationError

from . import FileEntry, WalkIncomplete, normalise_prefix


class LocalBackend:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve(strict=True)

    def _resolve(self, path: str) -> Path:
        candidate = (self._root / normalise_prefix(path)).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise ReadOnlyViolationError(f"path escapes the share root: {path!r}")
        return candidate

    def walk(self, prefix: str, limit: int) -> Iterator[FileEntry | WalkIncomplete]:
        """Files under `prefix`, at most `limit`. A folder it cannot read, a file that vanishes or
        a broken link does not stop the walk: it is left out and the walk says it is incomplete
        (QA-025). A link to a file outside the share is not a file of the share."""
        count = 0
        unreadable: list[OSError] = []
        for directory, subdirectories, files in os.walk(
            self._resolve(prefix), onerror=unreadable.append
        ):
            subdirectories.sort()
            for name in sorted(files):
                full = Path(directory) / name
                try:
                    if full.is_symlink():
                        self._resolve(full.relative_to(self._root).as_posix())
                    info = full.stat()
                except (OSError, ReadOnlyViolationError) as skipped:
                    yield WalkIncomplete(f"{name}: {type(skipped).__name__}")
                    continue
                if count >= limit:
                    yield WalkIncomplete(f"more than {limit} files")
                    return
                relative = full.relative_to(self._root).as_posix()
                yield FileEntry(relative, info.st_size, info.st_mtime)
                count += 1
        for error in unreadable:
            yield WalkIncomplete(f"unreadable folder: {type(error).__name__}")

    def read_head(self, path: str, nbytes: int) -> bytes:
        with self._resolve(path).open("rb") as handle:
            return handle.read(nbytes)

    def get_acl(self, path: str) -> dict[str, Any]:
        info = self._resolve(path).stat()
        return {"mode": oct(stat.S_IMODE(info.st_mode)), "uid": info.st_uid, "gid": info.st_gid}
