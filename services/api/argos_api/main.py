"""The API process of the appliance: the v1 and the console, from one origin (ADR-0012, ADR-0013).

This is where everything the routes ask for gets attached: the realm that exchanges the console's
authorization code, the Temporal client that starts and signals campaigns, the evidence service,
the AI gateway —reached over HTTP, the only service this API calls (ADR-0012)— and the Vault where
each webhook keeps its secret. What is not configured is simply not attached, and the route that
needs it answers 503 with the reason instead of pretending.

Usage: uv run python -m argos_api.main
"""

import os
from pathlib import Path
from typing import Any

import uvicorn
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from argos_api import SERVICE_NAME
from argos_api.app import create_app
from argos_api.assistant import AssistantClient
from argos_api.keycloak import Keycloak
from argos_api.routers import support, system
from argos_api.webhooks.worker import allowed_targets
from argos_auth import JwtValidator
from argos_common.config import ArgosConfig, Environment, get_config
from argos_common.dynamic_db import start_from_config
from argos_common.logs import configure_logging
from argos_common.secret_stores import VaultSecretStore
from argos_support import DiagnosticsStore

DEV_HOST = "127.0.0.1"
DEV_PORT = 8000
CAMPAIGN_QUEUE = "argos-campaigns"
CONSOLE = Path(os.environ.get("ARGOS_CONSOLE_DIR", "/app/console"))


class TemporalCampaigns:
    """What the API asks of Temporal, one connection per call: the API holds no workflow state."""

    def __init__(self, address: str, queue: str = CAMPAIGN_QUEUE) -> None:
        self._address = address
        self._queue = queue

    async def _client(self) -> Client:
        return await Client.connect(self._address, namespace="default")

    async def start(self, campaign_id: str) -> str:
        from argos_challenges.workflows import CampaignWorkflow

        client = await self._client()
        handle = await client.start_workflow(
            CampaignWorkflow.run,
            campaign_id,
            id=f"campaign-{campaign_id}",
            task_queue=self._queue,
        )
        return str(handle.id)

    async def signal(self, campaign_id: str, name: str, argument: str) -> None:
        client = await self._client()
        try:
            await client.get_workflow_handle(f"campaign-{campaign_id}").signal(name, argument)
        except RPCError as missing:
            # A remediation campaign has no workflow of that name: it polls its gates on its own.
            if missing.status != RPCStatusCode.NOT_FOUND:
                raise

    async def progress(self, campaign_id: str) -> dict[str, Any]:
        client = await self._client()
        handle = client.get_workflow_handle(f"campaign-{campaign_id}")
        answer: dict[str, Any] = await handle.query("progress")
        return answer

    async def remediate(self, scope: dict[str, Any]) -> str:
        from argos_challenges.workflows import RemediationRun

        client = await self._client()
        handle = await client.start_workflow(
            RemediationRun.run,
            scope,
            id=f"remediation-{scope.get('finding_id', scope.get('campaign_id', 'all'))}",
            task_queue=self._queue,
        )
        return str(handle.id)


def _evidence(cfg: ArgosConfig) -> Any:
    """The evidence service, when this appliance has its WORM store configured."""
    from argos_evidence.service import build_activities
    from argos_evidence.settings import EvidenceSettings

    try:
        settings = EvidenceSettings()
    except Exception:  # pragma: no cover - without the store there is no evidence to serve
        return None
    return build_activities(cfg, settings)


def build_app(cfg: ArgosConfig) -> Any:
    realm = Keycloak(cfg.OIDC_ISSUER)
    gateway = os.environ.get("ARGOS_AI_GATEWAY_URL")
    token = cfg.VAULT_TOKEN.get_secret_value() if cfg.VAULT_TOKEN else ""
    return create_app(
        JwtValidator(cfg.OIDC_ISSUER, cfg.OIDC_AUDIENCE),
        dsn=cfg.DATABASE_URL,
        refresher=realm.refresh,
        code_exchanger=realm.exchange,
        session_revoker=realm.logout,
        webhook_allowed=allowed_targets(cfg),
        campaign_runner=TemporalCampaigns(cfg.TEMPORAL_ADDRESS),
        evidence=_evidence(cfg),
        assistant=AssistantClient(gateway, tls_dir=cfg.TLS_DIR) if gateway else None,
        webhook_secrets=VaultSecretStore(cfg.VAULT_ADDR, token),
        console=CONSOLE,
        publish_docs=cfg.ENVIRONMENT is Environment.DEVELOPMENT,
        updates=_updates(cfg),
        support=_support(cfg),
    )


def _updates(cfg: ArgosConfig) -> system.UpdateRequests | None:
    """The updater's folders and the pinned release key, when this appliance takes updates."""
    if not cfg.UPDATE_DIR or not cfg.RELEASE_PUBLIC_KEY_FILE:
        return None
    base = Path(cfg.UPDATE_DIR)
    return system.UpdateRequests(
        inbox=base / "inbox",
        queue=base / "queue",
        state=base,
        release_key=Path(cfg.RELEASE_PUBLIC_KEY_FILE).read_bytes(),
    )


def _support(cfg: ArgosConfig) -> support.SupportDiagnostics | None:
    """The folder shared with the diagnostics collector and the key of support (ARG-088)."""
    if not cfg.SUPPORT_DIR or not cfg.SUPPORT_RECIPIENT_FILE:
        return None
    recipient = Path(cfg.SUPPORT_RECIPIENT_FILE).read_text(encoding="utf-8").strip()
    return support.SupportDiagnostics(DiagnosticsStore(Path(cfg.SUPPORT_DIR)), recipient)


def main() -> None:  # pragma: no cover - process entry point
    cfg = get_config()
    configure_logging(SERVICE_NAME, cfg.LOG_LEVEL)
    start_from_config(cfg)  # F09-05: the dynamic credential, before any connection
    # Inside a container the loopback address would hide the API from the published port; the
    # compose service sets ARGOS_API_BIND and docker keeps the port on 127.0.0.1.
    uvicorn.run(
        build_app(cfg),
        host=os.environ.get("ARGOS_API_BIND", DEV_HOST),
        port=DEV_PORT,
        log_config=None,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
