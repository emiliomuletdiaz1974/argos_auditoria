"""The assisted challenge generator: it proposes YAML that already compiles (ARG-056).

The 30-day norm-to-challenge SLA and the 300 challenges of GA do not come from writing YAML by hand:
this is the productivity tool of the normative team. The human flow rules — the jurist pastes the
obligation, the model proposes, the engineer reviews — and the key is that the jurist **only sees
proposals that already compile**. The proposal goes through the same `lint_challenge` the CI runs,
in memory, before it is shown; if it fails, one repair cycle with its errors.

A probe that writes is a different matter. It is not a mistake to repair: repairing it would teach
the model how to slip a write past the lint. It is refused outright, and the guardrails of ARG-060
refuse it again at the gateway if it ever got that far.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from argos_ai.gateway import Gateway
from argos_ai.guardrails import OutputRejectedError
from argos_challenges.dsl import SCHEMA_FILE, LintContext, lint_challenge, parse_challenge
from argos_challenges.library.translation import read_challenge, to_internal
from argos_ontology.vocabulary import LIBRARY_DIR

PROMPT_FILE = Path(__file__).resolve().parents[4] / "library" / "prompts" / "challenge_gen.yaml"
SERVICE = "challenge"
READ_ONLY = re.compile(r"^\s*(select|show|with)\b", re.IGNORECASE)
WRITES = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|merge)\b", re.IGNORECASE
)
PROBE_CATALOG = (
    "Sondas de conector: scan_schema, count, sample, check_config. "
    "Sondas internas, que leen lo que ARGOS ya sabe: shacl, inventory_query."
)
SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["yaml"],
    "additionalProperties": False,
    "properties": {"yaml": {"type": "string"}},
}
REPAIR = (
    "El reto que propusiste no pasa la validación de ARGOS. "
    "Corrígelo y devuelve el reto completo.\n"
    "Tu propuesta:\n{yaml}\nErrores:\n{errors}"
)


@dataclass(frozen=True, slots=True)
class ChallengeProposal:
    yaml: str
    valid: bool
    prompt_sha256: str
    warnings: list[str] = field(default_factory=list)


class _WritingProbeError(Exception):
    """The proposal declares a statement that is not a read."""


def _system_prompt() -> tuple[str, str]:
    raw = PROMPT_FILE.read_bytes()
    document = yaml.safe_load(raw.decode("utf-8"))
    examples = "\n---\n".join(
        (LIBRARY_DIR / "challenges" / name).read_text(encoding="utf-8")
        for name in document["examples"]
    )
    system = (
        f"{document['system']}\n\n{PROBE_CATALOG}\n\n"
        f"Esquema del DSL (JSON Schema):\n{SCHEMA_FILE.read_text(encoding='utf-8')}\n\n"
        f"Dos retos de la biblioteca como ejemplo:\n{examples}"
    )
    return system, hashlib.sha256(raw).hexdigest()


def _statements(document: Any) -> list[str]:
    """Every SQL statement a proposal declares, wherever it sits."""
    found: list[str] = []
    if isinstance(document, dict):
        for key, value in document.items():
            if key in ("statement", "sentencia") and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_statements(value))
    elif isinstance(document, list):
        for item in document:
            found.extend(_statements(item))
    return found


def check(text: str, context: LintContext) -> list[str]:
    """The errors of a proposal, as the CI would report them. Empty means it compiles."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"no es YAML válido: {exc}"]
    for statement in _statements(raw):
        if not READ_ONLY.match(statement) or WRITES.search(statement):
            raise _WritingProbeError(statement)
    try:
        spec = parse_challenge(to_internal(read_challenge(text)))
    except Exception as exc:  # noqa: BLE001 - every rejection of the DSL is a lint error here
        return [str(exc)]
    return lint_challenge(spec, context)


async def propose_challenge(
    obligation: str,
    text: str,
    gateway: Gateway,
    context: LintContext,
    regulation: str = "",
) -> ChallengeProposal:
    """A proposal for one obligation, shown only if it compiles."""
    system, digest = _system_prompt()
    user = f"Obligación {obligation}: {text}"
    if regulation:
        user += f"\n\nContexto normativo:\n{regulation}"
    try:
        answer = await gateway.chat_json(SERVICE, system, user, SCHEMA)
        proposal = str(answer.data["yaml"])
        errors = check(proposal, context)
        if errors:
            repair = REPAIR.format(yaml=proposal, errors="\n".join(errors))
            answer = await gateway.chat_json(SERVICE, system, f"{user}\n\n{repair}", SCHEMA)
            proposal = str(answer.data["yaml"])
            errors = check(proposal, context)
    except (_WritingProbeError, OutputRejectedError) as exc:
        return ChallengeProposal(
            "", False, digest, [f"propuesta rechazada: la sonda hace escritura ({exc})"]
        )
    return ChallengeProposal(proposal, not errors, digest, errors)


def proposal_id(text: str) -> tuple[str, str]:
    """(challenge id, family folder) of a valid proposal, to name its file."""
    document = to_internal(read_challenge(text))
    challenge_id = str(document["id"])
    return challenge_id, challenge_id.split("-", 1)[0]


def as_json(proposal: ChallengeProposal) -> str:
    return json.dumps(
        {
            "yaml": proposal.yaml,
            "valid": proposal.valid,
            "warnings": proposal.warnings,
            "prompt_sha256": proposal.prompt_sha256,
        },
        ensure_ascii=False,
    )
