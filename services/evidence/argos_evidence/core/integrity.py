"""Integrity of stored documents: canonical form and self-excluded hash (ARG-062, ARG-066, ARG-067).

Part of the pure verification core: no database, no store, no network. The
public verifier (ARG-069) uses it as it is.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from argos_common.journal import canonicalize


def canonical_instant(value: dt.datetime) -> str:
    """UTC with microseconds and a Z, the same shape as the journal."""
    if value.tzinfo is None:
        raise ValueError("the time must carry a time zone")
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def seal_document(document: Mapping[str, Any]) -> bytes:
    """Canonical bytes of ``document`` with its own SHA-256, computed without that field."""
    content = dict(document)
    content.pop("sha256", None)
    sealed = {**content, "sha256": file_digest(canonicalize(content).encode("utf-8"))}
    return canonicalize(sealed).encode("utf-8")


def file_digest(body: bytes) -> str:
    """SHA-256 of a stored file, as the index, the tree and the record name it."""
    return hashlib.sha256(body).hexdigest()


def verify_artifact(body: bytes) -> bool:
    """True when ``body`` is canonical and its inner hash matches the rest of it."""
    try:
        document = json.loads(body)
    except ValueError:
        return False
    if not isinstance(document, dict) or not isinstance(document.get("sha256"), str):
        return False
    try:
        if canonicalize(document).encode("utf-8") != body:
            return False
        content = canonicalize({k: v for k, v in document.items() if k != "sha256"})
    except ValueError:
        return False
    return file_digest(content.encode("utf-8")) == str(document["sha256"])
