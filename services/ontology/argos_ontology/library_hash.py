"""Fingerprint of the content library: which version of the rules a campaign measured with."""

import hashlib
from pathlib import Path

from argos_ontology.vocabulary import LIBRARY_DIR

VERSION_FILE = LIBRARY_DIR.parent / "VERSION"
PATTERNS = ("ontology/**/*.ttl", "policies/**/*.rego", "challenges/**/*.yaml")


def library_files(library_dir: Path = LIBRARY_DIR) -> list[Path]:
    found: list[Path] = []
    for pattern in PATTERNS:
        found.extend(path for path in library_dir.glob(pattern) if path.is_file())
    return sorted(set(found))


def library_fingerprint(library_dir: Path = LIBRARY_DIR) -> tuple[str, str]:
    """The version of the platform and the SHA-256 of the library content, in a stable order."""
    digest = hashlib.sha256()
    for path in library_files(library_dir):
        digest.update(path.relative_to(library_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    version = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else "0"
    return version, digest.hexdigest()
