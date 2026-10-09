"""The errors the API answers with: a stable code for programs, Spanish for people (ARG-071).

`code` is the contract: a front end decides on it, and it never changes with the wording. `title`
and `detail` are interface text, so they are written in Spanish (deviation ARG-071 from ADR-0005);
logs and domain exceptions stay in English.
"""

from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status

__all__ = ["TITLES", "ApiError", "ErrorCode", "generic_code", "title", "validation_detail"]


class ErrorCode(StrEnum):
    """Every code the API can answer. Renaming or removing one breaks its clients."""

    # Generic, one per status: what an error not yet given its own code answers.
    BAD_REQUEST = "bad_request"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNPROCESSABLE = "unprocessable"
    TOO_MANY_REQUESTS = "too_many_requests"
    INTERNAL_ERROR = "internal_error"
    NOT_IMPLEMENTED = "not_implemented"
    SERVICE_UNAVAILABLE = "service_unavailable"
    # Shared by every route.
    ROUTE_NOT_FOUND = "route_not_found"
    INVALID_REQUEST = "invalid_request"
    INVALID_VALUE = "invalid_value"
    STORE_UNAVAILABLE = "store_unavailable"
    ORIGIN_NOT_ALLOWED = "origin_not_allowed"
    # Who calls and with what (folder 12 of the collection).
    TOKEN_MISSING = "token_missing"  # noqa: S105 - an error code, not a secret
    TOKEN_INVALID = "token_invalid"  # noqa: S105 - an error code, not a secret
    AUTH_NOT_CONFIGURED = "auth_not_configured"
    SESSION_CLOSED = "session_closed"
    ROLE_MISSING = "role_missing"
    PERMISSION_DENIED = "permission_denied"
    ROLES_INCOMPATIBLE = "roles_incompatible"
    SECOND_FACTOR_REQUIRED = "second_factor_required"
    CURSOR_INVALID = "cursor_invalid"
    IDEMPOTENCY_KEY_INVALID = "idempotency_key_invalid"
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
    IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"
    SESSION_HEADER_MISSING = "session_header_missing"
    SESSION_COOKIE_MISSING = "session_cookie_missing"
    SESSION_REFUSED = "session_refused"
    SIGN_IN_REFUSED = "sign_in_refused"
    WEBHOOK_TARGET_NOT_ALLOWED = "webhook_target_not_allowed"


TITLES: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "Petición incorrecta",
    status.HTTP_401_UNAUTHORIZED: "No autenticado",
    status.HTTP_403_FORBIDDEN: "Prohibido",
    status.HTTP_404_NOT_FOUND: "No encontrado",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Método no permitido",
    status.HTTP_409_CONFLICT: "Conflicto",
    status.HTTP_413_CONTENT_TOO_LARGE: "Petición demasiado grande",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "Petición inválida",
    status.HTTP_429_TOO_MANY_REQUESTS: "Demasiadas peticiones",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "Error interno",
    status.HTTP_501_NOT_IMPLEMENTED: "No implementado",
    status.HTTP_503_SERVICE_UNAVAILABLE: "Servicio no disponible",
}

_GENERIC: dict[int, ErrorCode] = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.BAD_REQUEST,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHENTICATED,
    status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    status.HTTP_422_UNPROCESSABLE_CONTENT: ErrorCode.UNPROCESSABLE,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.TOO_MANY_REQUESTS,
    status.HTTP_500_INTERNAL_SERVER_ERROR: ErrorCode.INTERNAL_ERROR,
    status.HTTP_501_NOT_IMPLEMENTED: ErrorCode.NOT_IMPLEMENTED,
    status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCode.SERVICE_UNAVAILABLE,
}


class ApiError(HTTPException):
    """An error with its own code and a detail written for the person who reads it."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code, detail, headers)
        self.code = code


def title(status_code: int) -> str:
    return TITLES.get(status_code, "Error")


def generic_code(status_code: int) -> ErrorCode:
    if status_code in _GENERIC:
        return _GENERIC[status_code]
    return ErrorCode.INTERNAL_ERROR if status_code >= 500 else ErrorCode.BAD_REQUEST


# The reasons pydantic gives most often; anything else is just "not valid".
_REASONS: dict[str, str] = {
    "missing": "campo obligatorio",
    "extra_forbidden": "campo no admitido",
    "string_too_short": "texto demasiado corto",
    "string_too_long": "texto demasiado largo",
    "string_pattern_mismatch": "formato no válido",
    "string_type": "debe ser un texto",
    "enum": "valor no admitido",
    "literal_error": "valor no admitido",
    "uuid_parsing": "identificador no válido",
    "uuid_type": "identificador no válido",
    "int_parsing": "debe ser un número entero",
    "int_type": "debe ser un número entero",
    "bool_parsing": "debe ser verdadero o falso",
    "greater_than_equal": "valor demasiado pequeño",
    "less_than_equal": "valor demasiado grande",
    "too_short": "faltan elementos",
    "too_long": "demasiados elementos",
    "json_invalid": "JSON no válido",
    "datetime_parsing": "fecha no válida",
    "datetime_from_date_parsing": "fecha no válida",
    "model_attributes_type": "debe ser un objeto",
    "dict_type": "debe ser un objeto",
    "list_type": "debe ser una lista",
}


def _reason(error: dict[str, Any]) -> str:
    if error["type"] == "value_error":
        # A validator of ours: its message is the reason, and it names the field itself.
        return str(error["msg"]).removeprefix("Value error, ")
    return _REASONS.get(error["type"], "valor no válido")


def validation_detail(errors: list[dict[str, Any]]) -> str:
    """`body.to: campo obligatorio; query.limit: valor demasiado grande` — field and reason."""
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {_reason(e)}" for e in errors)
