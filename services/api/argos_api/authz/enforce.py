"""ARG-072 · reading the matrix and enforcing it, with denial as the default answer.

A route does not name roles: it names a permission. The matrix says which roles hold it, and it is
read once when the module loads, so a permission that nobody declared stops the API at start-up
instead of letting a request through.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException, Request, status

from argos_api.auth import CurrentIdentity
from argos_api.security_events import security_event
from argos_auth import ROLES, Identity

MATRIX_FILE = Path(__file__).with_name("permissions.yaml")


class AuthzError(Exception):
    """The matrix cannot be trusted: the API must not start."""


INCOMPATIBLE_KEY = "_incompatible_roles"
SECOND_FACTOR_KEY = "_second_factor"
# The roles whose people sign in with TOTP (DP-14): a permission that asks for a second factor may
# only be held by them, or it could never be exercised.
ROLES_WITH_TOTP = frozenset({"platform_admin", "dpo_reviewer"})
# RFC 9470: the token is valid, but it was not issued with the authentication the action needs.
STEP_UP = (
    'Bearer error="insufficient_user_authentication",'
    ' error_description="a second factor is required", acr_values="otp"'
)


def _raw(path: Path) -> dict[str, Any]:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise AuthzError(f"{path} does not hold a permission matrix")
    return raw


def load_incompatible(path: Path = MATRIX_FILE) -> tuple[frozenset[str], ...]:
    """Pairs (or sets) of roles that one person may not hold together."""
    groups = _raw(path).get(INCOMPATIBLE_KEY) or []
    parsed = []
    for group in groups:
        roles = frozenset(str(r) for r in group)
        if len(roles) < 2 or not roles <= set(ROLES):
            raise AuthzError(f"{INCOMPATIBLE_KEY} names an invalid group: {group}")
        parsed.append(roles)
    return tuple(parsed)


def load_matrix(path: Path = MATRIX_FILE) -> dict[str, frozenset[str]]:
    raw = _raw(path)
    matrix: dict[str, frozenset[str]] = {}
    for permission, roles in raw.items():
        if str(permission).startswith("_"):
            continue  # a declaration about the matrix, not a permission
        if not isinstance(roles, list) or not roles:
            raise AuthzError(f"{permission} grants nothing: remove it or give it a role")
        unknown = sorted(set(roles) - set(ROLES))
        if unknown:
            raise AuthzError(f"{permission} names roles outside the argos realm: {unknown}")
        matrix[str(permission)] = frozenset(roles)
    return matrix


def load_second_factor(
    matrix: dict[str, frozenset[str]], path: Path = MATRIX_FILE
) -> frozenset[str]:
    """The permissions that ask for a second factor (F09-07)."""
    listed = frozenset(str(p) for p in _raw(path).get(SECOND_FACTOR_KEY) or [])
    for permission in listed:
        if permission not in matrix:
            raise AuthzError(f"{SECOND_FACTOR_KEY} names an undeclared permission: {permission}")
        if not matrix[permission] <= ROLES_WITH_TOTP:
            raise AuthzError(f"{permission} asks for a second factor that some of its roles lack")
    return listed


PERMISSIONS: dict[str, frozenset[str]] = load_matrix()
INCOMPATIBLE: tuple[frozenset[str], ...] = load_incompatible()
SECOND_FACTOR: frozenset[str] = load_second_factor(PERMISSIONS)


@dataclass(frozen=True, slots=True)
class PermissionGuard:
    """The dependency of a route: it answers with the identity or with a 403."""

    permission: str
    roles: frozenset[str]

    def __call__(self, request: Request, identity: CurrentIdentity) -> Identity:
        if any(group <= identity.roles for group in INCOMPATIBLE):
            security_event(
                request,
                "authz.incompatible_roles",
                identity.actor,
                "refused",
                {"permission": self.permission},
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "this identity holds incompatible roles: planning and approving are two people",
            )
        if not identity.roles & self.roles:
            security_event(
                request, "authz.denied", identity.actor, "refused", {"permission": self.permission}
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"the permission {self.permission} is not yours"
            )
        if self.permission in SECOND_FACTOR and not identity.has_second_factor:
            # Only after the role check: the refusal says what to do, not which permission it was.
            security_event(
                request,
                "authz.second_factor_required",
                identity.actor,
                "refused",
                {"permission": self.permission},
            )
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "this action requires signing in with a second factor",
                {"WWW-Authenticate": STEP_UP},
            )
        if (
            request.method in ("POST", "PUT", "PATCH", "DELETE")
            and "platform_admin" in identity.roles
            and "platform_admin" in self.roles
        ):
            # Every use of an administration permission, allowed, stays in the security log.
            security_event(
                request,
                "authz.admin_action",
                identity.actor,
                "allowed",
                {"permission": self.permission},
            )
        # The route already knows who this is; the journal entry of the core route reads it here.
        request.state.identity = identity
        return identity


def require_perm(permission: str) -> PermissionGuard:
    if permission not in PERMISSIONS:
        raise AuthzError(f"{permission} is not declared in permissions.yaml")
    return PermissionGuard(permission, PERMISSIONS[permission])
