"""Systems: the catalogue of what ARGOS has discovered (ARG-073), and their registration (ARG-098).

`POST /systems` registers a system the appliance will audit. The size of the appliance limits how
many it holds (F10-08): beyond it the answer is a `409` with the figures and the options. The
credential never travels through the API: the system points at its secret in Vault
(`connectors/<id>`), which the installer or the operator fills.
"""

import asyncio
import json
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from argos_api.authz import require_perm
from argos_api.core import CoreRoute
from argos_api.http import caller, database
from argos_api.paging import Page, Paging, paginate
from argos_api.sizing import refuse_beyond
from argos_challenges.compiler import CONNECTOR_IDS
from argos_common.ids import uuid7
from argos_common.journal_pg import PostgresJournal
from argos_inventory.catalog.views import systems

router = APIRouter(prefix="/systems", tags=["systems"], route_class=CoreRoute)
MAX_CONFIG_BYTES = 8_192


class SystemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["rdbms", "files", "api", "directory", "clinical", "ai", "other"]
    environment: str = Field(default="production", min_length=1, max_length=40)
    owner: str | None = Field(default=None, max_length=120)
    connector: str = Field(min_length=1, max_length=120, description="one of the connectors")
    config: dict[str, Any] = Field(default_factory=dict)


@router.get(
    "", summary="List the registered systems", dependencies=[Depends(require_perm("systems.read"))]
)
def list_systems(request: Request, paging: Paging) -> Page:
    # One row more than asked: that is how the page knows whether there is a next one.
    rows = systems(database(request), paging.limit + 1, paging.position)
    return paginate(rows, paging.limit)


def _register(dsn: str, actor: str, body: SystemCreate) -> dict[str, Any]:
    system_id = str(uuid7())
    connection = {
        "secret": f"connectors/{system_id}",
        "connector": body.connector,
        "config": body.config,
    }
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.systems (id, name, kind, environment, owner, connection)"
            " VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
            (system_id, body.name, body.kind, body.environment, body.owner, json.dumps(connection)),
        )
    PostgresJournal(dsn).append(
        actor, "system.create", {"system": system_id, "name": body.name, "kind": body.kind}
    )
    return {
        "id": system_id,
        "name": body.name,
        "kind": body.kind,
        "connector": body.connector,
        "secret": connection["secret"],
    }


@router.post(
    "",
    summary="Register a system to audit, within the size of the appliance",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_perm("systems.create"))],
)
async def create_system(request: Request, body: SystemCreate) -> dict[str, Any]:
    if body.connector not in CONNECTOR_IDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unknown connector")
    if len(json.dumps(body.config)) > MAX_CONFIG_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "configuration too large")
    dsn = database(request)
    await asyncio.to_thread(refuse_beyond, request, dsn, "systems")
    return await asyncio.to_thread(_register, dsn, caller(request).actor, body)
