"""The single authenticated API of ARGOS: one door to the domain, under /api/v1 (ADR-0012).

There are no private routes for the console: what the console does, a client integration can do with
the same contract and the same authorisation. The contract is generated from this application and
versioned in `services/api/openapi.json`; `tools/api_contract.py --check` fails if they diverge.
"""

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import PlainTextResponse
from starlette.exceptions import HTTPException

from argos_airgap import Gate
from argos_api import API_PREFIX, API_VERSION, SERVICE_NAME
from argos_api.assistant import AssistantClient
from argos_api.authz import require_perm
from argos_api.core import MUTATIONS, IdempotencyStore
from argos_api.http import ERRORS, PROBLEM_MEDIA_TYPE, ProblemResponse, problem_response
from argos_api.routers import (
    airgap,
    approvals,
    assistant,
    campaigns,
    credentials,
    evidence,
    findings,
    inventory,
    security,
    session,
    support,
    synthetic,
    system,
    systems,
    webhooks,
)
from argos_api.routers.session import CodeExchanger, SessionRevoker
from argos_api.runner import CampaignRunner
from argos_api.security_events import backup_metrics, security_event, security_metrics
from argos_api.sessions import ClosedSessions, SessionClosures
from argos_api.webhooks.destination import Resolver, resolve_host
from argos_api.webhooks.store import SecretWriter
from argos_auth import JwtValidator
from argos_common import PostgresJournal
from argos_evidence.activities import EvidenceActivities

_log = logging.getLogger(__name__)

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
    synthetic.router,
    security.router,
    system.router,
    support.router,
    airgap.router,
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
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


def create_app(
    validator: JwtValidator | None = None,
    *,
    dsn: str | None = None,
    refresher: Refresher | None = None,
    campaign_runner: CampaignRunner | None = None,
    evidence: EvidenceActivities | None = None,
    assistant: AssistantClient | None = None,
    webhook_secrets: SecretWriter | None = None,
    code_exchanger: CodeExchanger | None = None,
    session_revoker: SessionRevoker | None = None,
    webhook_allowed: tuple[str, ...] = (),
    webhook_resolve: Resolver = resolve_host,
    console: Path | None = None,
    publish_docs: bool = False,
    updates: system.UpdateRequests | None = None,
    support: support.SupportDiagnostics | None = None,
    airgap: Gate | None = None,
    closed_sessions: SessionClosures | None = None,
) -> FastAPI:
    """The application. Without `dsn` there is no idempotency store and no journal: the routes
    still answer, and the tests that do not touch the database do not need one.

    The route map is served only when asked for (development): outside it, `/docs` and the served
    contract would describe routes and roles to anyone on the network, token or not. The versioned
    contract is still generated from `openapi()`, which does not depend on it being served.
    """
    app = FastAPI(
        title="ARGOS API",
        version=API_VERSION,
        description=DESCRIPTION,
        openapi_url=f"{API_PREFIX}/openapi.json" if publish_docs else None,
        docs_url=f"{API_PREFIX}/docs" if publish_docs else None,
        redoc_url=None,
    )
    app.state.validator = validator
    app.state.dsn = dsn
    app.state.updates = updates
    app.state.support = support
    app.state.airgap = airgap
    # F09-32: the sessions closed before their tokens expire, shared by every replica.
    app.state.closed_sessions = closed_sessions or (ClosedSessions(dsn) if dsn else None)
    app.state.refresher = refresher
    app.state.campaign_runner = campaign_runner
    app.state.evidence = evidence
    app.state.assistant = assistant
    app.state.webhook_secrets = webhook_secrets
    app.state.code_exchanger = code_exchanger
    app.state.session_revoker = session_revoker
    app.state.webhook_allowed = webhook_allowed
    app.state.webhook_resolve = webhook_resolve

    @app.middleware("http")
    async def _same_origin(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        """A mutation a page of another origin sends is refused before it runs (F09-15, SEC-058).

        The console lives on this origin (ADR-0013); browsers add `Origin` to every POST, and an
        opaque one (`null`) is another origin too. A client without a browser sends no `Origin`
        and is judged by its token alone.
        """
        origin = request.headers.get("origin")
        if (
            origin is not None
            and request.method in MUTATIONS
            and urlsplit(origin).netloc != request.headers.get("host", "")
        ):
            detail = {"origin": origin[:100]}
            security_event(request, "http.origin_refused", "anonymous", "refused", detail)
            return problem_response(
                request, status.HTTP_403_FORBIDDEN, _title(403), "a change sent from another origin"
            )
        return await call_next(request)

    @app.middleware("http")
    async def _security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        """The console and the API, from this one origin, with no frames and no sniffing (SEC-046).

        The route map of development loads its page from a CDN, so it keeps its own headers.
        """
        response = await call_next(request)
        if not (publish_docs and request.url.path == f"{API_PREFIX}/docs"):
            response.headers.update(SECURITY_HEADERS)
        return response

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

    @app.exception_handler(psycopg.Error)
    def _store_unavailable(request: Request, exc: psycopg.Error) -> ProblemResponse:
        # The driver's message names the host, the SQL or the constraint: it stays in the log, as
        # its type only, and the caller learns that the store did not answer.
        _log.warning("store error", extra={"error": type(exc).__name__})
        return problem_response(
            request,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            _title(status.HTTP_503_SERVICE_UNAVAILABLE),
            "the store is not available",
        )

    @app.get("/health", tags=["health"], summary="Liveness of the API")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME, "version": API_VERSION}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> PlainTextResponse:
        """What Prometheus scrapes on the internal network: the security log (F09-08)."""
        if not dsn:
            return PlainTextResponse("", status_code=503)
        text = security_metrics(dsn) + backup_metrics(dsn)
        return PlainTextResponse(text, media_type="text/plain; version=0.0.4")

    # Each route declares its permission (ARG-072); the guard resolves the identity on its way.
    for router in AUTHENTICATED:
        app.include_router(router, prefix=API_PREFIX, responses=ERRORS)
    app.include_router(session.router, prefix=API_PREFIX, responses=ERRORS)
    if dsn:
        app.include_router(
            _graph_router(dsn),
            prefix=f"{API_PREFIX}/inventory/graph",
            responses=ERRORS,
            dependencies=[Depends(require_perm("inventory.read"))],
        )

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
    if console is not None and (console / "index.html").is_file():
        _serve_console(app, console)
    return app


def _serve_console(app: FastAPI, built: Path) -> None:
    """The console as static files of this same origin (ADR-0013): no CDN, no second server.

    Its routes live in the browser, so any path that is not the API answers the single page and a
    reload of `/findings/<id>` works. Under the API prefix nothing is rewritten: an unknown route
    there is a problem+json, as every other error of the v1.
    """
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    page = built / "index.html"
    app.mount("/assets", StaticFiles(directory=built / "assets"), name="console-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def console_page(path: str) -> FileResponse:
        if f"/{path}".startswith(API_PREFIX):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no route /{path}")
        asked = (built / path).resolve()
        if path and asked.is_file() and asked.is_relative_to(built.resolve()):
            return FileResponse(asked)
        return FileResponse(page)


def _graph_router(dsn: str) -> APIRouter:
    """The graph keeps GraphQL (ARG-029): a neighbourhood of variable depth is not a REST resource.

    What changes here is the door: same token, same permission, mounted inside the v1.
    """
    from strawberry.fastapi import GraphQLRouter

    from argos_inventory.api.schema import build_schema
    from argos_inventory.graph.store import GraphStore

    store = GraphStore(dsn)

    async def context() -> dict[str, Any]:
        return {"store": store}

    router: GraphQLRouter[dict[str, Any], None] = GraphQLRouter(
        build_schema(), context_getter=context, graphql_ide=None
    )
    return router


def _title(code: int) -> str:
    return {
        status.HTTP_400_BAD_REQUEST: "bad request",
        status.HTTP_401_UNAUTHORIZED: "unauthenticated",
        status.HTTP_403_FORBIDDEN: "forbidden",
        status.HTTP_404_NOT_FOUND: "not found",
        status.HTTP_409_CONFLICT: "conflict",
        status.HTTP_501_NOT_IMPLEMENTED: "not implemented",
    }.get(code, "error")
