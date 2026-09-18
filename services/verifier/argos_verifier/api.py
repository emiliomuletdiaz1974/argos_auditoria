"""HTTP face of the public verifier (ARG-069): POST a bundle, get the report.

Stateless: no database, no store. The body is bounded, and nothing of what is
sent is kept or logged beyond its SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from argos_verifier.checks import verify_bundle

MAX_BUNDLE_BYTES = 16 * 1024 * 1024
log = logging.getLogger("argos_verifier")

app = FastAPI(title="ARGOS public verifier", docs_url=None, redoc_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/verify")
async def verify(request: Request) -> JSONResponse:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BUNDLE_BYTES:
        return JSONResponse({"error": "bundle too large"}, status_code=413)
    body = await request.body()
    if len(body) > MAX_BUNDLE_BYTES:
        return JSONResponse({"error": "bundle too large"}, status_code=413)
    try:
        bundle = json.loads(body)
    except ValueError:
        return JSONResponse({"error": "the bundle is not JSON"}, status_code=400)
    if not isinstance(bundle, dict):
        return JSONResponse({"error": "the bundle is not a JSON object"}, status_code=400)
    report = verify_bundle(bundle)
    log.info("bundle %s verified: ok=%s", hashlib.sha256(body).hexdigest(), report.ok)
    return JSONResponse(report.as_dict())
