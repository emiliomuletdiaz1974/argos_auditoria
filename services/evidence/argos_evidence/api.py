"""What the evidence service publishes so anyone can verify (ARG-068, ARG-070).

Only public material: the issuer's DID document, the signed status lists and
the credentials (which carry no personal data and are what a data space asset
points to). Dossiers and artifacts are not served here: they belong to the
client, who hands them over.

Usage: uv run python -m argos_evidence.api
"""

from __future__ import annotations

import os
import re
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException, Response

from argos_evidence.activities import EvidenceActivities

DEV_HOST = "127.0.0.1"
DEV_PORT = 8008
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def create_app(activities: EvidenceActivities, dsn: str) -> FastAPI:
    app = FastAPI(title="ARGOS evidence", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/.well-known/did.json")
    def did() -> dict[str, Any]:
        return activities.did_document()

    @app.get("/status/{number}")
    def status(number: int) -> dict[str, Any]:
        if number < 0 or not activities.status_list_exists(number):
            raise HTTPException(status_code=404)
        return activities.status_list(number)

    @app.get("/credentials/{credential}")
    def credential(credential: str) -> Response:
        if not _UUID.fullmatch(credential):
            raise HTTPException(status_code=404)
        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                "SELECT object_key, version_id FROM argos.credentials WHERE id = %s",
                (f"urn:uuid:{credential}",),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404)
        body = activities.stored(str(row[0]), str(row[1]))
        return Response(body, media_type="application/vc+json")

    return app


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    from argos_common.config import get_config
    from argos_common.logs import configure_logging
    from argos_evidence.service import build_activities
    from argos_evidence.settings import EvidenceSettings

    config = get_config()
    configure_logging("argos-evidence-api", config.LOG_LEVEL)
    app = create_app(build_activities(config, EvidenceSettings()), config.DATABASE_URL)
    uvicorn.run(
        app, host=os.environ.get("ARGOS_API_BIND", DEV_HOST), port=DEV_PORT, log_config=None
    )


if __name__ == "__main__":  # pragma: no cover
    main()
