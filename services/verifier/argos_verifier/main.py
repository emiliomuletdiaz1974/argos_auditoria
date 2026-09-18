"""Run the public verifier: uv run python -m argos_verifier.main.

It reads no platform configuration: it has no database, store or secret to
reach. Inside a container, compose sets ARGOS_API_BIND so the published port
(on 127.0.0.1 of the host) reaches it.
"""

import logging
import os

import uvicorn

from argos_verifier.api import app

DEV_HOST = "127.0.0.1"
DEV_PORT = 8007


def main() -> None:  # pragma: no cover - process entry point
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    uvicorn.run(app, host=os.environ.get("ARGOS_API_BIND", DEV_HOST), port=DEV_PORT)


if __name__ == "__main__":  # pragma: no cover
    main()
