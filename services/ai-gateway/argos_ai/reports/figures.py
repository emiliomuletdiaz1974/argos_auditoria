"""The figure verifier: every number of a draft must be a number of its data (ARG-057).

An invented figure in the record destroys the credibility of everything else, the deterministic
verdicts included. So the rule is blunt: a number the draft states has to be one of the numbers
it was given. Not a sum of them, not a ratio of them, not a rounded version of one — the model does
not do arithmetic for the record. What is tolerated is **format**: «1.200» is 1200, «0,85» is 0.85
and «85 %» may quote a ratio of 0.85, because refusing those would be a false positive.

Numbers inside identifiers (OBL-RGPD-32-1, sec-encryption-at-rest) and legal references
(«artículo 32», «art. 32.1.a») are not claims about quantities and are not checked.
"""

import math
import re
from collections.abc import Iterable

# A number standing on its own: not glued to a letter, a hyphen or another digit group.
_NUMBER = re.compile(
    r"(?<![\w\-.,])(\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?|\d+)(?![\w\-]|[.,]\d)"
    r"(\s*(?:%|por\s+ciento))?",
    re.IGNORECASE,
)
# A place in a law: «artículo 32», «art. 32.1.a», «apartado 2», «considerando 39». It names where
# something is written and says nothing about quantities, so it is not a figure.
_REFERENCE = re.compile(
    r"\b(?:art[íi]culos?|arts?\.|apartados?|considerandos?|anexos?|p[áa]rrafos?)"
    r"\s+(?:\d+(?:\.\d+)*(?:\.[a-z])?|[IVXLC]+)\b",
    re.IGNORECASE,
)


def _value(token: str) -> float:
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", token):
        return float(token.replace(".", ""))
    return float(token.replace(",", "."))


def extract_figures(text: str) -> list[tuple[str, float, bool]]:
    """(as written, value, is a percentage) for every figure of a text, in order."""
    text = _REFERENCE.sub(" ", text)
    return [(match[1], _value(match[1]), bool(match[2])) for match in _NUMBER.finditer(text)]


def _known(value: float, data: list[float]) -> bool:
    return any(math.isclose(value, known, rel_tol=0, abs_tol=1e-9) for known in data)


def unsupported_figures(text: str, data: Iterable[object]) -> list[str]:
    """The figures of the text that are not in the data, as written. Empty means it holds."""
    numbers: list[float] = []
    for item in data:
        try:
            numbers.append(float(str(item).replace(",", ".")))
        except ValueError:
            continue
    offending: list[str] = []
    for written, value, percentage in extract_figures(text):
        if _known(value, numbers) or (percentage and _known(value / 100, numbers)):
            continue
        offending.append(written)
    return offending
