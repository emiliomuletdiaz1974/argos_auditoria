"""Run the inventory API in development: uv run python -m argos_inventory.api.main."""

import uvicorn

from argos_auth import JwtValidator
from argos_common.config import get_config
from argos_common.logs import configure_logging
from argos_inventory.api.app import DEV_HOST, DEV_PORT, SERVICE_NAME, create_app
from argos_inventory.graph.store import GraphStore


def main() -> None:  # pragma: no cover - process entry point
    cfg = get_config()
    configure_logging(SERVICE_NAME, cfg.LOG_LEVEL)
    app = create_app(GraphStore(cfg.DATABASE_URL), JwtValidator(cfg.OIDC_ISSUER, cfg.OIDC_AUDIENCE))
    uvicorn.run(app, host=DEV_HOST, port=DEV_PORT, log_config=None)


if __name__ == "__main__":  # pragma: no cover
    main()
