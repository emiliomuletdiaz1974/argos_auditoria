"""Connector credentials live under Vault's connectors/ branch, readable only by the SDK policy
(ARG-009, P-04)."""

import uuid

from argos_common.secret_stores import SecretStore


def load_credentials(store: SecretStore, system_id: str) -> dict[str, str]:
    canonical = str(uuid.UUID(system_id))  # rejects paths smuggled in as ids
    return store.read(f"connectors/{canonical}")
