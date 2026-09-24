"""ARG-083 · nothing in ARGOS turns off the verification of a TLS peer (F09-06).

Mutual TLS is only worth what the weakest client makes of it: a `verify=False` or a `CERT_NONE`
would accept any server. This test reads the code and the configuration of the product and fails on
any of them. A mention that is not a use says why below.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ROOTS = ("libs", "services", "connectors", "tools", "deploy", "platform")
SUFFIXES = {".py", ".yaml", ".yml", ".sh", ".conf", ".toml"}
SKIPPED = {"tests", ".venv", "node_modules", "sources"}  # tests, dependencies and client sources
DISABLED = re.compile(
    r"verify\s*=\s*False|CERT_NONE|check_hostname\s*=\s*False|verify_mode\s*=\s*ssl\.CERT_OPTIONAL"
    r"|sslmode=(disable|allow|prefer|require)\b|TrustServerCertificate\s*=\s*yes|tls_insecure"
    r"|insecure_skip_verify\s*[:=]\s*true",
    re.IGNORECASE,
)
# Mentions that are not uses, each with its reason.
EXPLAINED = {
    "connectors/sql/argos_sql/generic.py": "the docstring says why sslmode=require is refused",
}


def _files() -> list[Path]:
    found = []
    for root in ROOTS:
        for path in (REPO / root).rglob("*"):
            parts = set(path.parts)
            if path.suffix in SUFFIXES and not parts & SKIPPED:
                found.append(path)
    return found


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_tls_verification_is_turned_off(path: Path) -> None:
    relative = path.relative_to(REPO).as_posix()
    hits = DISABLED.findall(path.read_text(encoding="utf-8", errors="ignore"))
    if relative in EXPLAINED:
        return
    assert not hits, f"{relative} turns off TLS verification: {hits}"
