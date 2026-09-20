"""ARG-072 · reading the matrix and enforcing it, with denial as the default answer.

A route does not name roles: it names a permission. The matrix says which roles hold it, and it is
read once when the module loads, so a permission that nobody declared stops the API at start-up
instead of letting a request through.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException, status

from argos_api.auth import CurrentIdentity
from argos_auth import ROLES, Identity

MATRIX_FILE = Path(__file__).with_name("permissions.yaml")


class AuthzError(Exception):
    """The matrix cannot be trusted: the API must not start."""


def load_matrix(path: Path = MATRIX_FILE) -> dict[str, frozenset[str]]:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise AuthzError(f"{path} does not hold a permission matrix")

    matrix: dict[str, frozenset[str]] = {}
    for permission, roles in raw.items():
        if not isinstance(roles, list) or not roles:
            raise AuthzError(f"{permission} grants nothing: remove it or give it a role")
        unknown = sorted(set(roles) - set(ROLES))
        if unknown:
            raise AuthzError(f"{permission} names roles outside the argos realm: {unknown}")
        matrix[str(permission)] = frozenset(roles)
    return matrix


PERMISSIONS: dict[str, frozenset[str]] = load_matrix()


@dataclass(frozen=True, slots=True)
class PermissionGuard:
    """The dependency of a route: it answers with the identity or with a 403."""

    permission: str
    roles: frozenset[str]

    def __call__(self, identity: CurrentIdentity) -> Identity:
        if not identity.roles & self.roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"the permission {self.permission} is not yours"
            )
        return identity


def require_perm(permission: str) -> PermissionGuard:
    if permission not in PERMISSIONS:
        raise AuthzError(f"{permission} is not declared in permissions.yaml")
    return PermissionGuard(permission, PERMISSIONS[permission])
