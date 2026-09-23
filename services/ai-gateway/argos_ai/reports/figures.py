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

# A number as people write it: «1.200», «97.3», «0,85», «15» in «15-20» or in «30días». What
# precedes it cannot be a letter, a digit or a decimal mark: «F09», «v2» and «32.1» are not claims.
_NUMBER = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?!\d|[.,]\d)"
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
# Names that carry digits: identifiers (OBL-RGPD-32-1, sec-encryption-at-rest, F09-28, v2), dates
# and the [n] that points to a source. None of them states a quantity.
_NOT_FIGURES = re.compile(
    r"(?<![\w-])[A-Za-z][\w]*(?:-[\w]+)+"
    r"|(?<![\w-])[A-Za-z_]+\d\w*"
    r"|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\[\d+\]"
)
# A quantity in words cannot be checked against the data, so it is never accepted: the draft has
# to write the number (security review F09-02, SEC-035). «Un», «una» and «uno» are left out: they
# are articles far more often than numbers.
_WORDS = re.compile(
    r"\b(?:dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince"
    r"|dieci\w+|veinte|veinti\w+|treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa"
    r"|cien|ciento|\w+cient[oa]s|quinient[oa]s|mil|mill[oó]n|millones)\b",
    re.IGNORECASE,
)


def _value(token: str) -> float:
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", token):
        return float(token.replace(".", "").replace(",", "."))
    return float(token.replace(",", "."))


def _blank(pattern: re.Pattern[str], text: str) -> str:
    """The text with what the pattern finds replaced by spaces, so positions do not move."""
    return pattern.sub(lambda match: " " * len(match.group(0)), text)


def _clean(text: str) -> str:
    return _blank(_NOT_FIGURES, _blank(_REFERENCE, text))


def extract_figures(text: str) -> list[tuple[str, float, bool]]:
    """(as written, value, is a percentage) for every figure of a text, in order."""
    return [
        (match[1], _value(match[1]), bool(match[2])) for match in _NUMBER.finditer(_clean(text))
    ]


def _known(value: float, data: list[float]) -> bool:
    return any(math.isclose(value, known, rel_tol=0, abs_tol=1e-9) for known in data)


def data_numbers(data: Iterable[object]) -> list[float]:
    """The numbers a text may quote: every value of the data that reads as one."""
    numbers: list[float] = []
    for item in data:
        try:
            numbers.append(float(str(item).replace(",", ".")))
        except ValueError:
            continue
    return numbers


def unsupported_figures(text: str, data: Iterable[object]) -> list[str]:
    """The figures of the text that are not in the data, as written and in order. Empty holds."""
    numbers = data_numbers(data)
    clean = _clean(text)
    offending: list[tuple[int, str]] = []
    for match in _NUMBER.finditer(clean):
        value, percentage = _value(match[1]), bool(match[2])
        if _known(value, numbers) or (percentage and _known(value / 100, numbers)):
            continue
        offending.append((match.start(1), match[1]))
    # «por ciento» is how a percentage is written, not a quantity in words.
    in_words = _blank(re.compile(r"por\s+ciento", re.IGNORECASE), clean)
    offending += [(match.start(), match.group(0)) for match in _WORDS.finditer(in_words)]
    return [written for _, written in sorted(offending)]
