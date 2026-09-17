"""The challenge library: families, generated catalog and frozen archive (ARG-050).

The catalog is no longer maintained by hand: it is generated from the challenges, so the matrix of
traceability of the ontology and the library can never drift apart. Ids that the populations already
cite but that have no challenge written yet stay in the catalog marked `draft: true`, with the
description they were reserved with.
"""

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from argos_challenges.dsl import (
    CHALLENGES_DIR,
    ChallengeSpec,
    library_challenges,
    load_challenge_file,
)
from argos_common.errors import ArgosError
from argos_ontology.traceability import ChallengeEntry

FAMILIES: Mapping[str, str] = {
    "acc": "access",
    "brc": "breach",
    "coh": "coherence",
    "doc": "documentation",
    "ds": "data_space",
    "dsr": "data_subject_rights",
    "ret": "retention",
    "sec": "security",
}
# The evidence a probe produces, unless the challenge declares another type.
EVIDENCE_BY_PROBE: Mapping[str, str] = {
    "scan_schema": "configuration",
    "check_config": "configuration",
    "count": "query_result",
    "sample": "query_result",
    "shacl": "query_result",
    "inventory_query": "query_result",
}
ARCHIVE_DIR = "archive"
HEADER = """# Catálogo de identificadores de retos, GENERADO desde la biblioteca (ARG-050).
# No se edita a mano: `uv run python tools/challenge_catalog.py` lo escribe y `--check` comprueba
# que está al día. Cada entrada es un id con su familia, el tipo de evidencia que produce y su
# descripción; `draft: true` marca un id que las poblaciones ya citan pero cuyo reto aún no existe.
# La matriz de trazabilidad de la ontología comprueba los `verificado_por` contra este fichero.
challenges:
"""


class ArchiveError(ArgosError):
    """A published version cannot change."""


def family_of(challenge_id: str) -> str:
    prefix = challenge_id.split("-")[0]
    if prefix not in FAMILIES:
        raise ArgosError(f"unknown challenge family: {prefix!r}")
    return FAMILIES[prefix]


def evidence_type_of(spec: ChallengeSpec) -> str:
    return EVIDENCE_BY_PROBE[spec.probe_kind]


def load_library(challenges_dir: Path = CHALLENGES_DIR) -> dict[str, ChallengeSpec]:
    """Every challenge of the library by id; the archive is history, never a source."""
    challenges: dict[str, ChallengeSpec] = {}
    for path in library_challenges(challenges_dir):
        if ARCHIVE_DIR in path.parts:
            continue
        spec = load_challenge_file(path)
        if spec.id in challenges:
            raise ArgosError(f"repeated challenge id in the library: {spec.id}")
        challenges[spec.id] = spec
    return dict(sorted(challenges.items()))


def build_catalog(
    challenges: Mapping[str, ChallengeSpec], reserved: Mapping[str, ChallengeEntry]
) -> dict[str, dict[str, Any]]:
    """The catalog: written challenges plus the ids still reserved, all sorted."""
    entries: dict[str, dict[str, Any]] = {}
    for challenge_id, spec in challenges.items():
        entries[challenge_id] = {
            "id": challenge_id,
            "family": family_of(challenge_id),
            "evidence_type": evidence_type_of(spec),
            "description": spec.title,
            "draft": False,
        }
    for challenge_id, entry in reserved.items():
        if challenge_id in entries:
            continue
        entries[challenge_id] = {
            "id": challenge_id,
            "family": entry.family,
            "evidence_type": entry.evidence_type,
            "description": entry.description,
            "draft": True,
        }
    return dict(sorted(entries.items()))


def catalog_yaml(entries: Mapping[str, Mapping[str, Any]]) -> str:
    lines = [HEADER]
    for entry in entries.values():
        description = str(entry["description"]).replace('"', "'")
        lines.append(
            f"  - id: {entry['id']}\n"
            f"    family: {entry['family']}\n"
            f"    evidence_type: {entry['evidence_type']}\n"
            f'    description: "{description}"\n'
            f"    draft: {str(bool(entry['draft'])).lower()}\n"
        )
    return "".join(lines)


def archive_library(library_dir: Path, version: str) -> int:
    """Freeze the current challenges under `archive/<version>/`. Returns the files written."""
    challenges_dir = library_dir / "challenges"
    target = challenges_dir / ARCHIVE_DIR / version
    written = 0
    for path in library_challenges(challenges_dir):
        if ARCHIVE_DIR in path.parts:
            continue
        destination = target / path.relative_to(challenges_dir)
        content = path.read_bytes()
        if destination.is_file():
            if destination.read_bytes() != content:
                raise ArchiveError(
                    f"the archived version {version} cannot change: {destination.name}"
                )
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        written += 1
    return written
