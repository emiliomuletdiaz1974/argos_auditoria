"""ARG-032 · version and hash checks happen before touching the database."""

from datetime import date

import pytest
from rdflib import Graph

from argos_ontology.store import OntologyStore, store_version

UNREACHABLE = "postgresql://nobody@127.0.0.1:9/none"
HASH = "a" * 64


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "1.0.0-rc1", "", "1.0.0 "])
def test_versions_must_be_plain_semver(version: str) -> None:
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        store_version(UNREACHABLE, version, date(2026, 1, 1), Graph(), HASH, {}, b"sig")


@pytest.mark.parametrize("sha256", ["A" * 64, "a" * 63, "g" * 64, ""])
def test_hashes_must_be_lowercase_sha256(sha256: str) -> None:
    with pytest.raises(ValueError, match="64 lowercase hex"):
        store_version(UNREACHABLE, "1.0.0", date(2026, 1, 1), Graph(), sha256, {}, b"sig")


def test_a_store_takes_a_version_or_a_date_not_both() -> None:
    with pytest.raises(ValueError, match="version or a date"):
        OntologyStore(UNREACHABLE, version="1.0.0", at=date(2026, 1, 1))
