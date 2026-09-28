"""Fingerprint of the content library: which version of the rules a campaign measured with."""

import hashlib
from pathlib import Path

from argos_ontology.vocabulary import LIBRARY_DIR

VERSION_FILE = LIBRARY_DIR.parent / "VERSION"
PATTERNS = ("ontology/**/*.ttl", "policies/**/*.rego", "challenges/**/*.yaml")


def library_files(library_dir: Path = LIBRARY_DIR) -> list[Path]:
    """The files of the library in the order of their POSIX paths, on every operating system.

    `Path` orders case-insensitively on Windows and the glob there ignores case too: the hash in
    the seal of a campaign must be the one anybody recomputes on Linux (QA-036).
    """
    found: set[Path] = set()
    for pattern in PATTERNS:
        suffix = pattern.rsplit("*", 1)[1]
        found.update(
            p for p in library_dir.glob(pattern) if p.is_file() and p.name.endswith(suffix)
        )
    return sorted(found, key=lambda p: p.relative_to(library_dir).as_posix())


def library_fingerprint(library_dir: Path = LIBRARY_DIR) -> tuple[str, str]:
    """The version of the platform and the SHA-256 of the library content, in a stable order."""
    digest = hashlib.sha256()
    for path in library_files(library_dir):
        digest.update(path.relative_to(library_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    version = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else "0"
    return version, digest.hexdigest()
