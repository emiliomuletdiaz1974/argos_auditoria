"""Inventory API service: read-only GraphQL over FastAPI with the uniform health endpoints."""

import asyncio
from importlib.metadata import version
from typing import Any

from fastapi import Depends, FastAPI
from strawberry.fastapi import GraphQLRouter

from argos_auth import JwtValidator
from argos_common.health import mount_health
from argos_inventory.api.auth import reader_dependency
from argos_inventory.api.schema import build_schema
from argos_inventory.graph.store import GraphStore

SERVICE_NAME = "argos-inventory"
DEV_HOST = "127.0.0.1"
DEV_PORT = 8002


def create_app(store: GraphStore, validator: JwtValidator) -> FastAPI:
    app = FastAPI(title=SERVICE_NAME)

    async def context() -> dict[str, Any]:
        return {"store": store}

    router: GraphQLRouter[dict[str, Any], None] = GraphQLRouter(
        build_schema(), context_getter=context, graphql_ide=None
    )
    app.include_router(
        router, prefix="/graphql", dependencies=[Depends(reader_dependency(validator))]
    )

    async def postgres_ok() -> bool:
        def probe() -> bool:
            with store.connection() as conn:
                return conn.execute("SELECT 1").fetchone() == (1,)

        return await asyncio.to_thread(probe)

    mount_health(app, SERVICE_NAME, version(SERVICE_NAME), {"postgres": postgres_ok})
    return app
