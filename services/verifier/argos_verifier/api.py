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
from fastapi.responses import JSONResponse

from argos_verifier.checks import Trust, verify_bundle

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
