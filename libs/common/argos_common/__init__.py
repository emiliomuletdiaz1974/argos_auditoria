"""ARGOS platform common library and core (components ARG-001 / ARG-005)."""

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
from .journal_pg import PostgresJournal
from .logs import configure_logging, get_logger

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
