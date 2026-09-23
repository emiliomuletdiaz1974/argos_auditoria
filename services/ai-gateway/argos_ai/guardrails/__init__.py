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

The answer is compared once normalised (NFKC, no format characters, no accents, lower case): a
zero-width space or a missing accent must not open a door (security review F09-02, SEC-034).
"""

import re
import unicodedata
from collections.abc import Callable, Collection, Mapping
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
    for table in ("identifiers", "verdict_patterns", "write_patterns"):
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
            # Separators are how people write identifiers; the validator judges the bare value.
            if not validator(re.sub(r"[ .\-/]", "", value).upper()):
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


def normalise(text: str, format_as_space: bool = False) -> str:
    """The text as the patterns see it: NFKC, no format characters, no accents, lower case.

    A zero-width character may stand between two words or hide inside one: `check_output` reads
    the text both ways, with them dropped and with them as spaces.
    """
    folded = unicodedata.normalize("NFKC", text)
    replacement = " " if format_as_space else ""
    visible = "".join(replacement if unicodedata.category(ch) == "Cf" else ch for ch in folded)
    bare = "".join(
        ch for ch in unicodedata.normalize("NFD", visible) if unicodedata.category(ch) != "Mn"
    )
    return " ".join(bare.lower().split())


@lru_cache(maxsize=4)
def _compiled(table: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(str(pattern)) for pattern in load_patterns()[table])


def _cited(
    answer: Mapping[str, Any],
    verdict_exists: Callable[[str], bool] | None,
    allowed_verdicts: Collection[str] | None = None,
) -> bool:
    """Whether the answer quotes verdicts. With a lookup, only verdicts that exist count: a
    model can write any id, and an invented one must not open the door to a claim. With
    `allowed_verdicts` (the assistant), only the ids its tools returned in this conversation
    count: an existing verdict of another campaign is not a source of this answer (SEC-034)."""
    ids = [answer.get("verdict_id")] if answer.get("verdict_id") else []
    listed = answer.get("verdict_ids") or []
    ids += listed if isinstance(listed, list) else [listed]
    if not ids:
        return False
    if allowed_verdicts is not None and not all(i in allowed_verdicts for i in ids):
        return False
    if verdict_exists is None:
        return True
    return all(isinstance(i, str) and verdict_exists(i) for i in ids)


def check_output(
    answer: Mapping[str, Any],
    verdict_exists: Callable[[str], bool] | None = None,
    allowed_verdicts: Collection[str] | None = None,
) -> bool:
    """True if the answer may leave the gateway; otherwise `OutputRejectedError` with its reason."""
    cited = _cited(answer, verdict_exists, allowed_verdicts)
    for text in _texts(answer):
        readings = {normalise(text), normalise(text, format_as_space=True)}
        claims = _compiled("verdict_patterns")
        if not cited and any(p.search(seen) for p in claims for seen in readings):
            raise OutputRejectedError("veredicto_no_citado")
        if any(p.search(seen) for p in _compiled("write_patterns") for seen in readings):
            raise OutputRejectedError("escritura_sobre_objetivo")
    return True
