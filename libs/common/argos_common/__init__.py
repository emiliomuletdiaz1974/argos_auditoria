"""ARGOS platform common library and core (components ARG-001 / ARG-005).

`PostgresJournal` is loaded on first use, not with the package: importing the pure parts (the
journal hash, canonical form, errors) must not pull in the PostgreSQL client, so that the public
verifier (ARG-069) can use them without a database driver.
"""

from typing import TYPE_CHECKING, Any

from .config import ApplianceSize, ArgosConfig, Environment, LogLevel, get_config, load_config
from .errors import ArgosError, ConfigurationError, IntegrityError
from .health import mount_health
from .journal import (
    GENESIS,
    Anomaly,
    JournalEntry,
    JournalVerificationError,
    VerificationResult,
    canonicalize,
    compute_hash,
    require_integrity,
    verify_entries,
)
from .logs import configure_logging, get_logger

if TYPE_CHECKING:
    from .journal_pg import PostgresJournal

__all__ = [
    "ArgosConfig",
    "Environment",
    "LogLevel",
    "ApplianceSize",
    "load_config",
    "get_config",
    "GENESIS",
    "Anomaly",
    "JournalEntry",
    "VerificationResult",
    "JournalVerificationError",
    "compute_hash",
    "canonicalize",
    "require_integrity",
    "verify_entries",
    "PostgresJournal",
    "ArgosError",
    "IntegrityError",
    "ConfigurationError",
    "configure_logging",
    "get_logger",
    "mount_health",
]


def __getattr__(name: str) -> Any:
    if name == "PostgresJournal":
        from .journal_pg import PostgresJournal

        return PostgresJournal
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
