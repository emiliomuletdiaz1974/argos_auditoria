"""Run the AI gateway service: uv run python -m argos_ai.api.main."""

import os

import uvicorn

from argos_ai.api.app import DEV_HOST, DEV_PORT, SERVICE_NAME, create_app
from argos_ai.backends.openai_compatible import OpenAiCompatibleBackend
from argos_ai.quotas import postgres_gateway
from argos_common.config import get_config
from argos_common.logs import configure_logging


def main() -> None:  # pragma: no cover - process entry point
    cfg = get_config()
    configure_logging(SERVICE_NAME, cfg.LOG_LEVEL)
    backend = OpenAiCompatibleBackend(str(cfg.LLM_LOCAL_ENDPOINT), cfg.LLM_MODEL)
    gateway = postgres_gateway(cfg.DATABASE_URL, backend, model=cfg.LLM_MODEL)
    # Inside a container the loopback address would hide the service from the published port;
    # compose sets ARGOS_API_BIND and keeps the port on 127.0.0.1 of the host.
    uvicorn.run(
        create_app(gateway),
        host=os.environ.get("ARGOS_API_BIND", DEV_HOST),
        port=DEV_PORT,
        log_config=None,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
