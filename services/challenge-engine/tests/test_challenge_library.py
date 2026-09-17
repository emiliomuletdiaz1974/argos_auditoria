"""ARG-050 · the library by families, the generated catalog and the frozen archive."""

import shutil
from pathlib import Path

import pytest
import yaml

from argos_challenges.library.catalog import (
    EVIDENCE_BY_PROBE,
    FAMILIES,
    ArchiveError,
    archive_library,
    build_catalog,
    catalog_yaml,
    load_library,
)
from argos_ontology.traceability import load_challenge_catalog, parse_challenge_catalog
from argos_ontology.vocabulary import LIBRARY_DIR

CATALOG_FILE = LIBRARY_DIR / "challenges" / "catalog.yaml"


@pytest.fixture
def library(tmp_path: Path) -> Path:
    copy = tmp_path / "library"
    shutil.copytree(LIBRARY_DIR, copy)
    return copy


def test_every_family_prefix_has_a_name() -> None:
    catalog = load_challenge_catalog()
    for entry in catalog.values():
        assert FAMILIES[entry.id.split("-")[0]] == entry.family, entry.id


def test_the_library_loads_the_challenges_by_id() -> None:
    challenges = load_library()
    assert {"ret-table-retention", "sec-encryption-at-rest"} <= set(challenges)
    assert all(challenge_id == spec.id for challenge_id, spec in challenges.items())


def test_the_generated_catalog_matches_the_one_shipped() -> None:
    generated = catalog_yaml(build_catalog(load_library(), load_challenge_catalog()))
    assert generated == CATALOG_FILE.read_text(encoding="utf-8")


def test_the_catalog_is_generated_from_the_challenges_and_keeps_the_rest_as_draft() -> None:
    entries = build_catalog(load_library(), load_challenge_catalog())
    written = entries["sec-encryption-at-rest"]
    assert written["draft"] is False
    assert written["family"] == "security"
    assert written["evidence_type"] == EVIDENCE_BY_PROBE["check_config"]
    reserved = entries["brc-breach-register"]
    assert reserved["draft"] is True


def test_the_generated_catalog_is_stable_and_valid_for_the_traceability() -> None:
    catalog = build_catalog(load_library(), load_challenge_catalog())
    text = catalog_yaml(catalog)
    assert catalog_yaml(build_catalog(load_library(), load_challenge_catalog())) == text
    parsed = parse_challenge_catalog(yaml.safe_load(text))
    assert set(parsed) == set(catalog)


def test_the_archive_freezes_a_version_and_refuses_to_change_it(library: Path) -> None:
    written = archive_library(library, "1.0.0")
    assert written > 0
    frozen = library / "challenges" / "archive" / "1.0.0" / "sec" / "sec-encryption-at-rest.yaml"
    assert frozen.is_file()
    assert archive_library(library, "1.0.0") == 0  # same content, nothing to do
    challenge = library / "challenges" / "sec" / "sec-encryption-at-rest.yaml"
    challenge.write_text(
        challenge.read_text(encoding="utf-8").replace('version: "1.0"', 'version: "1.1"'),
        encoding="utf-8",
    )
    with pytest.raises(ArchiveError, match="1.0.0"):
        archive_library(library, "1.0.0")


def test_the_archive_is_not_a_source_of_challenges(library: Path) -> None:
    archive_library(library, "1.0.0")
    challenges_dir = library / "challenges"
    challenges = load_library(challenges_dir)
    sources = [
        spec.source.relative_to(challenges_dir) for spec in challenges.values() if spec.source
    ]
    assert sources and not any("archive" in path.parts for path in sources)
