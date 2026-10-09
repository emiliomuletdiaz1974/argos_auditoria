"""The errors the API answers with: a stable code for programs, Spanish for people (ARG-071).

`code` is the contract: a front end decides on it, and it never changes with the wording. `title`
and `detail` are interface text, so they are written in Spanish (deviation ARG-071 from ADR-0005);
logs and domain exceptions stay in English.
"""

from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status

from argos_common.errors import ArgosError

__all__ = [
    "DOMAIN_ERRORS",
    "TITLES",
    "ApiError",
    "ErrorCode",
    "domain_error",
    "generic_code",
    "title",
    "validation_detail",
]


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
    # Campaigns and gates (folder 03).
    ACTOR_NOT_PERSON = "actor_not_person"
    CAMPAIGN_NOT_FOUND = "campaign_not_found"
    CAMPAIGN_RUNNER_UNAVAILABLE = "campaign_runner_unavailable"
    CAMPAIGN_ALREADY_RUNNING = "campaign_already_running"
    REMEDIATION_ALREADY_RUNNING = "remediation_already_running"
    CAMPAIGN_PLAN_NOT_READY = "campaign_plan_not_ready"
    CAMPAIGN_NOT_RUNNING = "campaign_not_running"
    CAMPAIGN_NOT_PLANNED = "campaign_not_planned"
    CAMPAIGN_TRANSITION_ILLEGAL = "campaign_transition_illegal"
    CAMPAIGN_CLOSED = "campaign_closed"
    GATE_NOT_REQUESTED = "gate_not_requested"
    GATE_ALREADY_APPROVED = "gate_already_approved"
    SAME_PERSON_APPROVAL = "same_person_approval"
    VERDICT_CONFLICT = "verdict_conflict"
    # The synthetic subject (folders 03 and 07, ADR-0008).
    SYNTHETIC_SUBJECT_NOT_FOUND = "synthetic_subject_not_found"
    SYNTHETIC_SUBJECT_NOT_IN_CAMPAIGN = "synthetic_subject_not_in_campaign"
    SYNTHETIC_SUBJECTS_ALREADY_GENERATED = "synthetic_subjects_already_generated"
    SYNTHETIC_CAMPAIGN_CLOSED = "synthetic_campaign_closed"
    SYNTHETIC_REVERT_PROCEDURE_MISSING = "synthetic_revert_procedure_missing"
    SYNTHETIC_INJECTION_NOT_FOUND = "synthetic_injection_not_found"
    SYNTHETIC_INJECTION_NOT_CONFIRMED = "synthetic_injection_not_confirmed"
    SYNTHETIC_SAME_PERSON_CONFIRMATION = "synthetic_same_person_confirmation"
    SYNTHETIC_ALREADY_CONFIRMED = "synthetic_already_confirmed"
    SYNTHETIC_RIGHT_UNKNOWN = "synthetic_right_unknown"
    SYNTHETIC_TIMEZONE_MISSING = "synthetic_timezone_missing"
    SYNTHETIC_DATES_IN_FUTURE = "synthetic_dates_in_future"
    SYNTHETIC_ANSWER_BEFORE_REQUEST = "synthetic_answer_before_request"


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


# How a person reads the states and gates the details name.
CAMPAIGN_STATUS = {
    "planned": "planificada",
    "pinned": "fijada",
    "running": "en ejecución",
    "sealed": "sellada",
    "failed": "fallida",
}
GATE_LABELS = {"start": "Inicio de la campaña", "sampling": "Muestreo (doble control)"}

_CONFLICT = status.HTTP_409_CONFLICT
_NOT_FOUND = status.HTTP_404_NOT_FOUND
_INVALID = status.HTTP_422_UNPROCESSABLE_CONTENT

# The refusals of the domain, by their stable code (`ArgosError.code`): what the API answers.
# `{name}` takes the value of `details[name]`, already put into words.
DOMAIN_ERRORS: dict[str, tuple[int, ErrorCode, str]] = {
    "actor_not_person": (
        status.HTTP_403_FORBIDDEN,
        ErrorCode.ACTOR_NOT_PERSON,
        "Esta acción solo la puede hacer una persona, no un servicio.",
    ),
    "campaign_not_found": (
        _NOT_FOUND,
        ErrorCode.CAMPAIGN_NOT_FOUND,
        "La campaña {campaign_id} no existe.",
    ),
    "campaign_not_planned": (
        _CONFLICT,
        ErrorCode.CAMPAIGN_NOT_PLANNED,
        "La campaña ya no está planificada: no se puede fijar de nuevo.",
    ),
    "campaign_transition_illegal": (
        _CONFLICT,
        ErrorCode.CAMPAIGN_TRANSITION_ILLEGAL,
        "La campaña no puede pasar de «{from}» a «{to}».",
    ),
    "campaign_status_unknown": (
        _CONFLICT,
        ErrorCode.CAMPAIGN_TRANSITION_ILLEGAL,
        "La campaña no puede pasar a un estado que no existe.",
    ),
    "campaign_closed": (
        _CONFLICT,
        ErrorCode.CAMPAIGN_CLOSED,
        "La campaña está {status} y no admite más aprobaciones.",
    ),
    "gate_not_requested": (
        _CONFLICT,
        ErrorCode.GATE_NOT_REQUESTED,
        "La compuerta «{gate}» no se ha solicitado.",
    ),
    "gate_already_approved": (
        _CONFLICT,
        ErrorCode.GATE_ALREADY_APPROVED,
        "Ya aprobó la compuerta «{gate}»: la segunda aprobación es de otra persona.",
    ),
    "same_person_approval": (
        _CONFLICT,
        ErrorCode.SAME_PERSON_APPROVAL,
        "Quien creó la campaña no puede aprobarla: hace falta otra persona.",
    ),
    "verdict_missing": (
        _CONFLICT,
        ErrorCode.VERDICT_CONFLICT,
        "El veredicto no se pudo leer después de escribirlo.",
    ),
    "verdict_conflict": (
        _CONFLICT,
        ErrorCode.VERDICT_CONFLICT,
        "La unidad ya tiene un veredicto distinto.",
    ),
    "synthetic_subject_without_campaign": (
        _CONFLICT,
        ErrorCode.SYNTHETIC_SUBJECT_NOT_IN_CAMPAIGN,
        "Un sujeto sintético se registra siempre para una campaña.",
    ),
    "synthetic_revert_procedure_missing": (
        _INVALID,
        ErrorCode.SYNTHETIC_REVERT_PROCEDURE_MISSING,
        "Una inyección solo se autoriza con su procedimiento para revertirla.",
    ),
    "synthetic_subject_not_in_campaign": (
        _CONFLICT,
        ErrorCode.SYNTHETIC_SUBJECT_NOT_IN_CAMPAIGN,
        "El sujeto no pertenece a esta campaña.",
    ),
    "synthetic_injection_not_found": (
        _NOT_FOUND,
        ErrorCode.SYNTHETIC_INJECTION_NOT_FOUND,
        "La inyección {injection_id} no existe.",
    ),
    "synthetic_same_person_confirmation": (
        _CONFLICT,
        ErrorCode.SYNTHETIC_SAME_PERSON_CONFIRMATION,
        "Quien autorizó la inyección no puede confirmarla: lo hace el cliente.",
    ),
    "synthetic_injection_not_confirmed": (
        _CONFLICT,
        ErrorCode.SYNTHETIC_INJECTION_NOT_CONFIRMED,
        "El sujeto aún no está inyectado: confirme antes la inyección.",
    ),
    "synthetic_already_confirmed": (
        _CONFLICT,
        ErrorCode.SYNTHETIC_ALREADY_CONFIRMED,
        "Este paso ya está confirmado para la inyección.",
    ),
    "synthetic_right_unknown": (
        _INVALID,
        ErrorCode.SYNTHETIC_RIGHT_UNKNOWN,
        "El derecho «{right}» no existe.",
    ),
    "synthetic_timezone_missing": (
        _INVALID,
        ErrorCode.SYNTHETIC_TIMEZONE_MISSING,
        "La fecha «{field}» necesita su zona horaria.",
    ),
    "synthetic_dates_in_future": (
        _INVALID,
        ErrorCode.SYNTHETIC_DATES_IN_FUTURE,
        "Las fechas del ejercicio de un derecho no pueden ser futuras.",
    ),
    "synthetic_answer_before_request": (
        _INVALID,
        ErrorCode.SYNTHETIC_ANSWER_BEFORE_REQUEST,
        "La respuesta no puede ser anterior a la solicitud.",
    ),
    "synthetic_campaign_closed": (
        _CONFLICT,
        ErrorCode.SYNTHETIC_CAMPAIGN_CLOSED,
        "La campaña está {status} y no admite sujetos nuevos.",
    ),
    "synthetic_subjects_already_generated": (
        _CONFLICT,
        ErrorCode.SYNTHETIC_SUBJECTS_ALREADY_GENERATED,
        "Los sujetos de esta campaña ya se generaron.",
    ),
}


class _Words(dict[str, str]):
    """The details put into words; a value the domain did not give is left as a dash."""

    def __missing__(self, key: str) -> str:
        return "—"


def _words(details: dict[str, object]) -> _Words:
    words = _Words()
    for key, value in details.items():
        text = str(value)
        if key in ("status", "from", "to"):
            text = CAMPAIGN_STATUS.get(text, text)
        elif key == "gate":
            text = GATE_LABELS.get(text, text)
        words[key] = text
    return words


def domain_error(refused: ArgosError) -> ApiError:
    """The answer to a refusal of the domain: its own code and a detail in Spanish.

    A code the API does not know yet answers a generic conflict, never the English of the domain.
    """
    known = DOMAIN_ERRORS.get(refused.code)
    if known is None:
        return ApiError(
            _CONFLICT, ErrorCode.CONFLICT, "La operación no es posible en el estado actual."
        )
    status_code, code, template = known
    return ApiError(status_code, code, template.format_map(_words(refused.details)))
