"""The single authenticated API of ARGOS: one door to the domain, under /api/v1 (ADR-0012).

There are no private routes for the console: what the console does, a client integration can do with
the same contract and the same authorisation. The contract is generated from this application and
versioned in `services/api/openapi.json`; `tools/api_contract.py --check` fails if they diverge.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from starlette.exceptions import HTTPException

from argos_api import API_PREFIX, API_VERSION, SERVICE_NAME
from argos_api.core import IdempotencyStore
from argos_api.http import ERRORS, PROBLEM_MEDIA_TYPE, ProblemResponse, problem_response
from argos_api.routers import (
    approvals,
    assistant,
    campaigns,
    credentials,
    evidence,
    findings,
    inventory,
    session,
    systems,
    webhooks,
)
from argos_auth import JwtValidator
from argos_common import PostgresJournal

DEV_HOST = "127.0.0.1"
DEV_PORT = 8009
AUTHENTICATED = (
    systems.router,
    inventory.router,
    campaigns.router,
    findings.router,
    evidence.router,
    credentials.router,
    assistant.router,
    approvals.router,
    webhooks.router,
)
DESCRIPTION = (
    "Campaigns, inventory, findings and evidence of the ARGOS appliance. "
    "Listings paginate by opaque cursor, errors follow RFC 9457 and every POST that creates "
    "accepts an Idempotency-Key."
)


def _as_problem(document: dict[str, Any]) -> dict[str, Any]:
    """FastAPI documents every response as `application/json`; the errors are problem+json."""
    for methods in document["paths"].values():
        for operation in methods.values():
            for code, response in operation.get("responses", {}).items():
                content = response.get("content")
                if not code.isdigit() or int(code) < 400 or not content:
                    continue
                schema = content.pop("application/json", None)
                if schema is not None:
                    content[PROBLEM_MEDIA_TYPE] = schema
    return document


Refresher = Callable[[str], Awaitable[dict[str, Any]]]


def create_app(
    validator: JwtValidator | None = None,
    *,
    dsn: str | None = None,
    refresher: Refresher | None = None,
) -> FastAPI:
    """The application. Without `dsn` there is no idempotency store and no journal: the routes
    still answer, and the tests that do not touch the database do not need one."""
    app = FastAPI(
        title="ARGOS API",
        version=API_VERSION,
        description=DESCRIPTION,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.validator = validator
    app.state.refresher = refresher
    app.state.idempotency = IdempotencyStore(dsn) if dsn else None
    app.state.journal = PostgresJournal(dsn) if dsn else None

    # Starlette's HTTPException covers FastAPI's, so the 404 of an unknown route is a problem too.
    @app.exception_handler(HTTPException)
    def _http_error(request: Request, exc: HTTPException) -> ProblemResponse:
        status_code = exc.status_code
        response = problem_response(request, status_code, _title(status_code), exc.detail)
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(RequestValidationError)
    def _invalid_body(request: Request, exc: RequestValidationError) -> ProblemResponse:
        return problem_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid request",
            "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()),
        )

    @app.get("/health", tags=["health"], summary="Liveness of the API")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME, "version": API_VERSION}

    # Each route declares its permission (ARG-072); the guard resolves the identity on its way.
    for router in AUTHENTICATED:
        app.include_router(router, prefix=API_PREFIX, responses=ERRORS)
    app.include_router(session.router, prefix=API_PREFIX, responses=ERRORS)

    def contract() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = _as_problem(
                get_openapi(
                    title=app.title,
                    version=app.version,
                    description=app.description,
                    routes=app.routes,
                )
            )
        return app.openapi_schema

    app.openapi = contract  # type: ignore[method-assign]
    return app


def _title(code: int) -> str:
    return {
        status.HTTP_400_BAD_REQUEST: "bad request",
        status.HTTP_401_UNAUTHORIZED: "unauthenticated",
        status.HTTP_403_FORBIDDEN: "forbidden",
        status.HTTP_404_NOT_FOUND: "not found",
        status.HTTP_409_CONFLICT: "conflict",
        status.HTTP_501_NOT_IMPLEMENTED: "not implemented",
    }.get(code, "error")
