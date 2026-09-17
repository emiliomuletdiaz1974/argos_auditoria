"""Run the campaign API in development: uv run python -m argos_challenges.api.main."""

import os

import uvicorn
from temporalio.client import Client

from argos_auth import JwtValidator
from argos_challenges.api.app import DEV_HOST, DEV_PORT, SERVICE_NAME, create_app
from argos_challenges.workflows import CampaignWorkflow, RemediationRun
from argos_common.config import get_config
from argos_common.logs import configure_logging

TASK_QUEUE = "argos-campaigns"


def main() -> None:  # pragma: no cover - process entry point
    cfg = get_config()
    configure_logging(SERVICE_NAME, cfg.LOG_LEVEL)

    async def start(campaign_id: str) -> str:
        client = await Client.connect(cfg.TEMPORAL_ADDRESS, namespace="default")
        handle = await client.start_workflow(
            CampaignWorkflow.run,
            campaign_id,
            id=f"campaign-{campaign_id}",
            task_queue=TASK_QUEUE,
        )
        return str(handle.id)

    async def signal(campaign_id: str, name: str, argument: str) -> None:
        client = await Client.connect(cfg.TEMPORAL_ADDRESS, namespace="default")
        await client.get_workflow_handle(f"campaign-{campaign_id}").signal(name, argument)

    async def remediate(scope: dict[str, object]) -> str:
        client = await Client.connect(cfg.TEMPORAL_ADDRESS, namespace="default")
        handle = await client.start_workflow(
            RemediationRun.run,
            scope,
            id=f"remediation-{scope.get('campaign_id', 'all')}",
            task_queue=TASK_QUEUE,
        )
        return str(handle.id)

    app = create_app(
        cfg.DATABASE_URL,
        JwtValidator(cfg.OIDC_ISSUER, cfg.OIDC_AUDIENCE),
        start_campaign=start,
        signal_campaign=signal,
        start_remediation=remediate,
    )
    # Inside a container the loopback address would hide the API from the published port;
    # the compose service sets ARGOS_API_BIND and docker keeps the port on 127.0.0.1.
    uvicorn.run(
        app, host=os.environ.get("ARGOS_API_BIND", DEV_HOST), port=DEV_PORT, log_config=None
    )


if __name__ == "__main__":  # pragma: no cover
    main()
