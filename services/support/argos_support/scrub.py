"""Everything free that goes into the diagnostic package passes through here (ARG-088).

Defence in depth: no service should log personal data or secrets, but the package does not trust
it. In this order:

1. the values of the secrets the collector saw in the environment of each service, whole;
2. credentials inside URLs, JSON Web Tokens, `Bearer` headers and `password=…`-style pairs;
3. e-mail addresses, with a stable marker per address;
4. the Spanish identifiers of the guardrails (ARG-060): only what validates is replaced.

The identifiers table is the one the AI gateway uses (`library/prompts/guardrails.yaml`), read
here through the connector SDK so the package never imports the AI layer (ADR-0012).
"""

import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from argos_common.errors import ArgosError
from argos_connector.validators import scrub_identifiers

IDENTIFIERS_FILE = Path(__file__).resolve().parents[3] / "library" / "prompts" / "guardrails.yaml"
# A value shorter than this is not replaced by value (it would destroy ordinary words); the
# patterns below still catch it where it sits next to its name.
MIN_SECRET_LENGTH = 6
SECRET_NAME = re.compile(r"(?i)pass(word|wd)?|secret|token|key|credential|dsn|database_url|auth")
SECRET = "[SECRET]"  # noqa: S105 - the marker that replaces a secret, not one

_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+@"), "[CREDENTIALS]@"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), "[JWT]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + SECRET),
    (
        re.compile(
            r"(?i)\b([\w-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)[\w-]*)"
            r"(\"?\s*[=:]\s*\"?)([^\s\"',;&}]+)"
        ),
        r"\1\2" + SECRET,
    ),
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_URL_PASSWORD = re.compile(r"://[^/\s:@]+:([^/\s@]+)@")


@lru_cache(maxsize=1)
def identifier_table(path: Path = IDENTIFIERS_FILE) -> tuple[Mapping[str, Any], ...]:
    """The identifiers of the guardrails. Missing is an error: nothing leaves unscrubbed."""
    table = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("identifiers")
    if not table:
        raise ArgosError(f"the diagnostic package needs the identifiers table of {path}")
    return tuple(table)


def secret_values(env: Mapping[str, str]) -> set[str]:
    """The values of an environment that are secrets: by the name, and passwords inside URLs."""
    found: set[str] = set()
    for name, value in env.items():
        if SECRET_NAME.search(name) and len(value) >= MIN_SECRET_LENGTH:
            found.add(value)
        found.update(m for m in _URL_PASSWORD.findall(value) if len(m) >= MIN_SECRET_LENGTH)
    return found


class Scrubber:
    """`scrubber(text) -> (clean text, substitutions)`, the same rules for every file."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        # Longest first: a secret that contains another is replaced whole.
        self._secrets = sorted(
            {s for s in secrets if len(s) >= MIN_SECRET_LENGTH}, key=len, reverse=True
        )

    def __call__(self, text: str) -> tuple[str, int]:
        substitutions = 0
        for secret in self._secrets:
            substitutions += text.count(secret)
            text = text.replace(secret, SECRET)
        for pattern, replacement in _RULES:
            text, count = pattern.subn(replacement, text)
            substitutions += count
        seen: dict[str, str] = {}

        def email(match: re.Match[str]) -> str:
            return seen.setdefault(match.group(0), f"[EMAIL-{len(seen) + 1}]")

        text, count = _EMAIL.subn(email, text)
        substitutions += count
        text, count = scrub_identifiers(text, identifier_table())
        return text, substitutions + count

    def tree(self, value: Any) -> tuple[Any, int]:
        """Every string of a JSON value, however deep, scrubbed before it is serialised."""
        if isinstance(value, str):
            return self(value)
        if isinstance(value, Mapping):
            total, out = 0, {}
            for key, item in value.items():
                out[key], count = self.tree(item)
                total += count
            return out, total
        if isinstance(value, list | tuple):
            items = [self.tree(item) for item in value]
            return [item for item, _ in items], sum(count for _, count in items)
        return value, 0
