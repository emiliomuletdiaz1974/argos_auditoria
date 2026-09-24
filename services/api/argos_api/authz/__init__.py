"""Authorisation of the v1: one versioned matrix and nothing else (ARG-072)."""

from argos_api.authz.enforce import (
    MATRIX_FILE,
    PERMISSIONS,
    SECOND_FACTOR,
    AuthzError,
    PermissionGuard,
    load_matrix,
    require_perm,
)

__all__ = [
    "MATRIX_FILE",
    "PERMISSIONS",
    "SECOND_FACTOR",
    "AuthzError",
    "PermissionGuard",
    "load_matrix",
    "require_perm",
]
