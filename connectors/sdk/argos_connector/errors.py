"""Budget and circuit errors of the connector SDK (ARG-011, ARG-013)."""

from typing import Any

from argos_common.errors import ArgosError


class BudgetExceededError(ArgosError):
    """The probe is outside its window or the rate budget is exhausted: wait, do not fail."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="BUDGET_EXCEEDED", details=details)


class CircuitOpenError(ArgosError):
    """The customer system is responding slowly: ARGOS steps aside until the cooldown ends."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="CIRCUIT_OPEN", details=details)
