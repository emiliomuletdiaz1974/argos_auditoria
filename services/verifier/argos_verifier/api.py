"""HTTP face of the public verifier (ARG-069): POST a bundle, get the report.

Stateless: no database, no store. The body is bounded while it is read (a chunked
body gets no further than the limit), and nothing of what is sent is kept or
logged beyond its SHA-256. What the verifier trusts comes from the file named by
ARGOS_VERIFIER_TRUST_FILE, read on each request so a new key is picked up
without a restart; without it, nothing verifies.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from argos_verifier import norms
from argos_verifier.checks import Trust, verify_bundle

MAX_BUNDLE_BYTES = 16 * 1024 * 1024
log = logging.getLogger("argos_verifier")
PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Vary": "Accept",
}

# The verifier is public, but its route map is not a service: nothing is served but the routes
# (F09-15, SEC-059), as the evidence service and the API outside development.
app = FastAPI(title="ARGOS public verifier", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/verify")
def verify_page(dossier: str | None = None) -> Response:
    """Where the QR of a printed dossier lands: which dossier it names and how to check it."""
    if dossier is not None and not norms.DIGEST.match(dossier):
        page = norms.verify_page(None).replace(
            "<h1>Comprobar un expediente</h1>",
            "<h1>Comprobar un expediente</h1><p class=notice>El código no es un SHA-256.</p>",
        )
        return Response(page, status_code=400, media_type="text/html", headers=PAGE_HEADERS)
    return Response(norms.verify_page(dossier), media_type="text/html", headers=PAGE_HEADERS)


@app.post("/verify")
async def verify(request: Request) -> JSONResponse:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BUNDLE_BYTES:
        return JSONResponse({"error": "bundle too large"}, status_code=413)
    received = bytearray()
    async for chunk in request.stream():
        received += chunk
        if len(received) > MAX_BUNDLE_BYTES:
            return JSONResponse({"error": "bundle too large"}, status_code=413)
    body = bytes(received)
    try:
        bundle = json.loads(body)
    except ValueError:
        return JSONResponse({"error": "the bundle is not JSON"}, status_code=400)
    if not isinstance(bundle, dict):
        return JSONResponse({"error": "the bundle is not a JSON object"}, status_code=400)
    report = verify_bundle(bundle, Trust.from_file(os.environ.get("ARGOS_VERIFIER_TRUST_FILE")))
    log.info("bundle %s verified: ok=%s", hashlib.sha256(body).hexdigest(), report.ok)
    return JSONResponse(report.as_dict())


@app.get("/norms/")
def norms_front_page() -> Response:
    return Response(norms.front_page(), media_type="text/html", headers=PAGE_HEADERS)


@app.get("/norms/catalogo.md")
def norms_markdown() -> Response:
    headers = {
        **PAGE_HEADERS,
        "Content-Disposition": 'attachment; filename="catalogo-normativo.md"',
    }
    return Response(norms.markdown(), media_type="text/markdown", headers=headers)


@app.get("/norms/catalogo.pdf")
def norms_pdf() -> Response:
    headers = {
        **PAGE_HEADERS,
        "Content-Disposition": 'attachment; filename="catalogo-normativo.pdf"',
    }
    return Response(norms.pdf(), media_type="application/pdf", headers=headers)


@app.get("/norms/{name}")
def norm(name: str, request: Request) -> Response:
    """The IRI `https://ns.argos.eu/norms/{name}`, dereferenced: a page, Turtle or JSON-LD."""
    iri = norms.node(name)
    if iri is None:
        return JSONResponse({"error": "not in the namespace"}, status_code=404)
    accept = request.headers.get("accept", "")
    graph = norms.population()
    if "text/turtle" in accept:
        content = norms.description(graph, iri).serialize(format="turtle")
        return Response(content, media_type="text/turtle", headers=PAGE_HEADERS)
    if "application/ld+json" in accept:
        content = norms.description(graph, iri).serialize(format="json-ld")
        return Response(content, media_type="application/ld+json", headers=PAGE_HEADERS)
    return Response(norms.page(graph, iri), media_type="text/html", headers=PAGE_HEADERS)
