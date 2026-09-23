"""Guardrails: personal data out of the prompts, verdicts and writes out of the answers (ARG-060).

Defence in depth of the two prohibitions of the layer. The layers before this one already minimise
—what reaches the model is metadata, counts and hashes— but a column name can hold a real DNI (it
happens: columns created by mistake), and a client document can bring identifiers with it.

On the way in, `scrub_input` replaces what **validates** as a Spanish identifier with a stable
marker, reusing the validators of ARG-024. Blind regular expressions would destroy an innocent
product code that happens to look like a DNI; a validator does not.

On the way out, `check_output` refuses two things: a claim of conformity about an asset that does
not quote the verdict it comes from, and an instruction to write on a client system. Both tables
are versioned content (`library/prompts/guardrails.yaml`), so the team widens them without a
release. The decision to reject is not content: it has no switch.
"""

import re
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from argos_common.errors import ArgosError
from argos_connector.validators import VALIDATORS

PATTERNS_FILE = Path(__file__).resolve().parents[4] / "library" / "prompts" / "guardrails.yaml"


class OutputRejectedError(ArgosError):
    """The model answered something the product does not let through."""


@lru_cache(maxsize=1)
def load_patterns(path: Path = PATTERNS_FILE) -> dict[str, Any]:
    """The pattern tables, as content. A table that is missing is an error, not an empty default."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    for table in ("identifiers", "verdict_words", "write_verbs"):
        if not document.get(table):
            raise ArgosError(f"the guardrails need the table {table!r}")
    return dict(document)


def scrub_input(text: str) -> tuple[str, int]:
    """The text with every validated identifier replaced, and how many were replaced.

    The same value always receives the same marker inside one text: a different marker each time
    would destroy the meaning of the sentence for the model, which is the point of scrubbing and
    not simply deleting.
    """
    patterns = load_patterns()
    clean = text
    substitutions = 0
    for entry in patterns["identifiers"]:
        marker, validator = str(entry["marker"]), VALIDATORS[str(entry["validator"])]
        seen: dict[str, str] = {}
        matches = list(re.finditer(str(entry["pattern"]), clean))
        for match in reversed(matches):
            value = match.group(0)
            if not validator(value.upper()):
                continue
            if value not in seen:
                seen[value] = f"[{marker}-{len(seen) + 1}]"
            clean = clean[: match.start()] + seen[value] + clean[match.end() :]
            substitutions += 1
    return clean, substitutions


def _texts(value: Any) -> list[str]:
    """Every string of a JSON answer, however deep it sits."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for item in value.values() for text in _texts(item)]
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    return []


def _cited(answer: Mapping[str, Any], verdict_exists: Callable[[str], bool] | None) -> bool:
    """Whether the answer quotes verdicts. With a lookup, only verdicts that exist count: a
    model can write any id, and an invented one must not open the door to a claim."""
    ids = [answer.get("verdict_id")] if answer.get("verdict_id") else []
    listed = answer.get("verdict_ids") or []
    ids += listed if isinstance(listed, list) else [listed]
    if not ids:
        return False
    if verdict_exists is None:
        return True
    return all(isinstance(i, str) and verdict_exists(i) for i in ids)


def check_output(
    answer: Mapping[str, Any], verdict_exists: Callable[[str], bool] | None = None
) -> bool:
    """True if the answer may leave the gateway; otherwise `OutputRejectedError` with its reason."""
    patterns = load_patterns()
    cited = _cited(answer, verdict_exists)
    for text in _texts(answer):
        lowered = " ".join(text.lower().split())
        if not cited and any(word in lowered for word in patterns["verdict_words"]):
            raise OutputRejectedError("veredicto_no_citado")
        if any(verb in lowered for verb in patterns["write_verbs"]):
            raise OutputRejectedError("escritura_sobre_objetivo")
    return True
