"""Open the read-only connector of a registered system (ARG-022, deviation note ARG-021-023)."""

import importlib
from dataclasses import dataclass
from typing import Any

import psycopg

from argos_common.secret_stores import SecretStore
from argos_connector.base import Connector
from argos_connector.budget import LoadBudget
from argos_connector.context import ConnectorContext
from argos_connector.credentials import load_credentials
from argos_connector.journal import QueryJournal
from argos_connector.minimize import ValueHasher
from argos_connector.probes import ProbeResult, ProbeSpec

# The catalog names a class; only ARGOS connector packages may be imported from it.
ALLOWED_CONNECTOR_PACKAGES = (
    "argos_sql.",
    "argos_files.",
    "argos_rest.",
    "argos_ldap.",
    "argos_fhir.",
    "argos_dicom.",
)


@dataclass(frozen=True, slots=True)
class RegisteredSystem:
    id: str
    name: str
    kind: str
    connector: str  # "package.module:Class"
    config: dict[str, Any]


def load_system(dsn: str, system_id: str) -> RegisteredSystem:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT id::text, name, kind, connection FROM argos.systems WHERE id = %s",
            (system_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"unknown system: {system_id}")
    connection: dict[str, Any] = row[3]
    return RegisteredSystem(
        id=str(row[0]),
        name=str(row[1]),
        kind=str(row[2]),
        connector=str(connection.get("connector", "")),
        config=dict(connection.get("config", {})),
    )


def connector_class(path: str) -> type[Connector]:
    module_name, _, class_name = path.partition(":")
    if not class_name or not module_name.startswith(ALLOWED_CONNECTOR_PACKAGES):
        raise ValueError(f"connector not allowed: {path!r}")
    try:
        candidate = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError):
        raise ValueError(f"connector not found: {path!r}") from None
    if not (isinstance(candidate, type) and issubclass(candidate, Connector)):
        raise ValueError(f"not a connector class: {path!r}")
    return candidate


def open_connector(dsn: str, store: SecretStore, system: RegisteredSystem) -> Connector:
    cls = connector_class(system.connector)
    credentials = load_credentials(store, system.id)
    context = ConnectorContext(
        journal=QueryJournal(dsn, system.id),
        budget=LoadBudget(system.id, dict(system.config.get("budget", {}))),
        hasher=ValueHasher.from_hex(credentials["hash_key"]),
        credentials=credentials,
    )
    config = {key: value for key, value in system.config.items() if key != "budget"}
    connector = cls(system.id, config, context)
    connector.open()
    return connector


def run_probe(dsn: str, store: SecretStore, system_id: str, spec: ProbeSpec) -> ProbeResult:
    connector = open_connector(dsn, store, load_system(dsn, system_id))
    try:
        return connector.execute(spec)
    finally:
        connector.close()
