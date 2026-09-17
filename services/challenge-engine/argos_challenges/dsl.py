"""The challenge DSL: schema, model and the extra rules of the product (ARG-041).

The JSON Schema is the law of the format; the extra rules are what a schema cannot express: a
challenge points at an obligation that cites it back, at an asset class that exists and, when the
criterion delegates, at a Rego package that is shipped. Both run in CI and when the library loads.
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
from rdflib import URIRef

from argos_challenges.library.translation import read_challenge, to_internal
from argos_common.errors import ArgosError
from argos_ontology.applicability import asset_classes, load_asset_classes
from argos_ontology.traceability import library_graph
from argos_ontology.vocabulary import ARGOS, LIBRARY_DIR, NORMS

CHALLENGES_DIR = LIBRARY_DIR / "challenges"
SCHEMA_FILE = CHALLENGES_DIR / "schema" / "challenge.schema.json"
POLICIES_DIR = LIBRARY_DIR / "policies"


class ChallengeError(ArgosError):
    """The document is not a valid challenge."""


@dataclass(frozen=True, slots=True)
class ChallengeSpec:
    id: str
    version: str
    title: str
    obligation: str
    asset_class: str
    probe_kind: str
    params: dict[str, Any]
    by_connector: dict[str, dict[str, Any]]
    criterion: dict[str, Any]
    capture: tuple[str, ...]
    minimisation: str
    severity: str
    sampling: dict[str, Any] | None
    approval_required: bool
    preconditions: tuple[str, ...]
    estimated_cost: dict[str, int]
    source: Path | None = None

    @property
    def opa_package(self) -> str | None:
        opa = self.criterion.get("opa")
        return None if opa is None else str(opa["package"])


@dataclass(frozen=True, slots=True)
class LintContext:
    obligations: dict[str, frozenset[str]]  # obligation -> challenge ids it verifies
    asset_classes: frozenset[str]
    packages: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_library(cls, library_dir: Path = LIBRARY_DIR) -> "LintContext":
        graph = library_graph(library_dir)
        obligations: dict[str, frozenset[str]] = {}
        for obligation in set(graph.subjects(ARGOS.severity, None)):
            if not isinstance(obligation, URIRef):
                continue
            challenges = {
                str(graph.value(ch, ARGOS.challengeId))
                for ch in graph.objects(obligation, ARGOS.verifiedBy)
            }
            obligations[str(obligation).removeprefix(str(NORMS))] = frozenset(challenges)
        graph_of_classes = load_asset_classes(_asset_classes_file(library_dir))
        classes = {
            str(entry.iri).removeprefix(str(NORMS)) for entry in asset_classes(graph_of_classes)
        }
        packages = {
            f"argos.{path.stem}"
            for path in (library_dir / "policies").glob("*.rego")
            if not path.name.endswith("_test.rego")
        }
        return cls(obligations, frozenset(classes), frozenset(packages))


def _asset_classes_file(library_dir: Path) -> Path:
    return library_dir / "ontology" / "asset-classes" / "base.ttl"


@lru_cache(maxsize=1)
def load_schema(path: Path = SCHEMA_FILE) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def parse_challenge(document: Any, source: Path | None = None) -> ChallengeSpec:
    """Validate a document against the schema and freeze it into a spec."""
    if not isinstance(document, dict):
        raise ChallengeError("a challenge is a mapping")
    validator = jsonschema.Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        where = "/".join(str(part) for part in errors[0].absolute_path) or "(root)"
        raise ChallengeError(f"{where}: {errors[0].message}")
    probe = document["probe"]
    evidence = document["evidence"]
    return ChallengeSpec(
        id=document["id"],
        version=document["version"],
        title=document["title"],
        obligation=document["objective"]["obligation"],
        asset_class=document["selector"]["asset_class"],
        probe_kind=probe["kind"],
        params=dict(probe.get("params", {})),
        by_connector={k: dict(v) for k, v in probe.get("by_connector", {}).items()},
        criterion=dict(document["criterion"]),
        capture=tuple(evidence["capture"]),
        minimisation=evidence["minimisation"],
        severity=document["severity"],
        sampling=dict(document["sampling"]) if "sampling" in document else None,
        approval_required=bool(document.get("approval_required", False)),
        preconditions=tuple(document.get("preconditions", ())),
        estimated_cost=dict(document.get("estimated_cost", {})),
        source=source,
    )


def load_challenge_file(path: Path) -> ChallengeSpec:
    """Read a challenge from disk: Spanish layer first, then the schema."""
    document = to_internal(read_challenge(path.read_text(encoding="utf-8")))
    return parse_challenge(document, source=path)


def library_challenges(challenges_dir: Path = CHALLENGES_DIR) -> list[Path]:
    """Every challenge file of the library, without the schema or the generated catalog."""
    return sorted(
        path
        for path in challenges_dir.rglob("*.yaml")
        if "schema" not in path.parts and path.name != "catalog.yaml"
    )


def lint_challenge(
    spec: ChallengeSpec, context: LintContext, path: Path | None = None
) -> list[str]:
    """The product rules a schema cannot express. Returns one message per breach, sorted."""
    errors: list[str] = []
    if spec.probe_kind == "sample" and not spec.approval_required:
        errors.append(f"{spec.id}: a sample probe needs approval_required: true")
    if "hashed_sample" in spec.capture and spec.probe_kind != "sample":
        errors.append(f"{spec.id}: hashed_sample is only captured by a sample probe")
    verifiers = context.obligations.get(spec.obligation)
    if verifiers is None:
        errors.append(f"{spec.id}: unknown obligation {spec.obligation}")
    elif spec.id not in verifiers:
        errors.append(f"{spec.id}: the obligation {spec.obligation} does not cite this challenge")
    if spec.asset_class not in context.asset_classes:
        errors.append(f"{spec.id}: unknown asset class {spec.asset_class}")
    package = spec.opa_package
    if package is not None and package not in context.packages:
        errors.append(f"{spec.id}: unknown Rego package {package}")
    target = path if path is not None else spec.source
    if target is not None and target.stem != spec.id:
        errors.append(f"{spec.id}: the file is named {target.name}, not {spec.id}.yaml")
    return sorted(errors)
