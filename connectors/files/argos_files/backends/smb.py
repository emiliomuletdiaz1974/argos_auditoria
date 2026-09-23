"""SMB backend: scandir-based walk, one round trip per directory instead of per file (ARG-017)."""

from collections.abc import Iterator, Mapping
from datetime import UTC
from typing import Any

import smbclient

from . import FileEntry, normalise_prefix


class SmbBackend:
    def __init__(self, credentials: Mapping[str, str], encrypt: bool | None = True) -> None:
        self._server = credentials["server"]
        self._share = credentials["share"]
        self._port = int(credentials.get("port", "445"))
        smbclient.register_session(
            self._server,
            username=credentials["username"],
            password=credentials["password"],
            port=self._port,
            encrypt=encrypt,
        )

    def close(self) -> None:
        smbclient.delete_session(self._server, port=self._port)

    def _unc(self, path: str) -> str:
        relative = normalise_prefix(path).replace("/", "\\")
        root = f"\\\\{self._server}\\{self._share}"
        return f"{root}\\{relative}" if relative else root

    def walk(self, prefix: str, limit: int) -> Iterator[FileEntry]:
        """Files under `prefix`, at most `limit` entries: files and directories listed both count.

        A tree of empty directories, or a loop of links, would otherwise be listing requests
        without end under a single probe (SEC-053). Links are listed, never followed.
        """
        count = 0
        pending = [normalise_prefix(prefix)]
        while pending:
            if count >= limit:
                return
            current = pending.pop()
            listing = smbclient.scandir(self._unc(current), port=self._port)
            count += 1
            for entry in sorted(listing, key=lambda e: e.name):
                relative = f"{current}/{entry.name}" if current else entry.name
                if entry.is_dir(follow_symlinks=False):
                    pending.append(relative)
                    continue
                if entry.is_symlink():
                    continue
                # Use the listing's own metadata: SMBDirEntry.stat() reconnects without our port
                # and would reach whatever SMB server listens on 445 of the same host.
                info = entry.smb_info
                written = info.last_write_time
                if written.tzinfo is None:
                    written = written.replace(tzinfo=UTC)
                yield FileEntry(relative, int(info.end_of_file), written.timestamp())
                count += 1
                if count >= limit:
                    return

    def read_head(self, path: str, nbytes: int) -> bytes:
        with smbclient.open_file(self._unc(path), mode="rb", port=self._port) as handle:
            return bytes(handle.read(nbytes))

    def get_acl(self, path: str) -> dict[str, Any]:
        info = smbclient.stat(self._unc(path), port=self._port)
        return {"mode": oct(info.st_mode), "note": "full security descriptor requires smbcacls"}
