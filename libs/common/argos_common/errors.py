"""Typed exception hierarchy for the ARGOS platform (component ARG-001)."""

from typing import Any


class ArgosError(Exception):
    """Root exception for every handled error in the ARGOS platform."""

    def __init__(
        self,
        message: str,
        code: str = "ARGOS_GENERIC_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


class ConfigurationError(ArgosError):
    """Raised when a configuration parameter or secret is invalid or missing."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="CONFIGURATION_ERROR", details=details)


class IntegrityError(ArgosError):
    """Raised when a hash, signature or chained entry is corrupted."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="INTEGRITY_ERROR", details=details)


class ReadOnlyViolationError(ArgosError):
    """Raised if a connector or activity attempts a write operation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="READ_ONLY_VIOLATION", details=details)


class SecretNotAccessibleError(ArgosError):
    """The secret does not exist or the caller lacks permission: deliberately indistinguishable."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="SECRET_NOT_ACCESSIBLE", details=details)
