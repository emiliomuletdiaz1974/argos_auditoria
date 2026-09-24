"""The importers of the airlock: each verifies its own signature before anything is applied.

- `update_importer`: the archive is unpacked with the `data` filter of `tarfile` (no absolute
  paths, no `..`, no links out, no devices), verified with **the same** `verify_bundle` of the
  updater (F09-10) and queued for it, as `POST /api/v1/system/updates` does. The updater verifies
  again when it applies.
- `content_importer`: `load_bundle` of ARG-040, which checks the pinned fingerprint and the
  signature, refuses a rollback, and only then stores the version.
- `tsr_importer`: each reply is matched to the queued object whose name it carries and verified by
  `accept_reply` (status, chain to a trusted root, nonce and the SHA-256 of the stored object).
"""

import hashlib
import json
import shutil
import tarfile
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

from argos_updater import verify_bundle

__all__ = ["content_importer", "tsr_importer", "tsr_name", "update_importer", "verify_bundle"]


def tsr_name(object_key: str) -> str:
    """The file name of the query and of the reply of an object: its key does not fit a name."""
    return hashlib.sha256(object_key.encode("utf-8")).hexdigest()[:32] + ".tsr"


def update_importer(
    inbox: Path,
    queue: Path,
    installed: Callable[[], str | None],
    release_key: bytes,
) -> Callable[[Path, str], str]:
    def import_update(archive: Path, actor: str) -> str:
        unpacked = archive.parent / "bundle"
        with tarfile.open(archive) as tar:
            tar.extractall(unpacked, filter="data")  # refuses what would leave the folder
        verified = verify_bundle(unpacked, release_key, installed())
        target = inbox / f"bundle-{verified.version}"
        if target.exists():
            raise FileExistsError(f"bundle {verified.version} is already in the inbox")
        shutil.move(str(unpacked), str(target))
        ident = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        queue.mkdir(parents=True, exist_ok=True)
        temporary = queue / f".{ident}.tmp"
        request = {
            "bundle": target.name,
            "version": verified.version,
            "allow_downgrade": False,
            "requested_by": actor,
            "via": "airgap",
        }
        temporary.write_text(json.dumps(request), encoding="utf-8")
        temporary.replace(queue / f"{ident}.json")
        return f"update {verified.version} verified and queued for the updater"

    return import_update


def content_importer(
    load: Callable[[bytes, bytes], str],
) -> Callable[[Path, str], str]:
    """`load(bundle, signature)`: `load_bundle` with the DSN, the key and its pinned fingerprint."""

    def import_content(bundle: Path, actor: str) -> str:
        signature = bundle.with_name(bundle.name + ".sig").read_bytes()
        version = load(bundle.read_bytes(), signature)
        return f"content {version} verified and loaded"

    return import_content


def tsr_importer(
    queued: Callable[[], Iterable[str]],
    accept: Callable[[str, bytes], None],
) -> Callable[[Path, str], str]:
    """`accept(object_key, reply)` verifies and keeps the token, or raises."""

    def import_reply(reply: Path, actor: str) -> str:
        wanted = {tsr_name(key): key for key in queued()}
        object_key = wanted.get(reply.name)
        if object_key is None:
            raise LookupError("no queued object has this name: nothing asked for this reply")
        accept(object_key, reply.read_bytes())
        return f"time stamp of {object_key} verified and kept"

    return import_reply
