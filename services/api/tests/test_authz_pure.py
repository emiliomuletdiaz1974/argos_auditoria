"""ARG-072 · the matrix on its own: deny by default and refuse anything it cannot understand."""

from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from argos_api.authz import PERMISSIONS, AuthzError, PermissionGuard, load_matrix, require_perm
from argos_auth import ROLES, Identity

MATRIX = Path(__file__).resolve().parents[1] / "argos_api" / "authz" / "permissions.yaml"


def _identity(*roles: str) -> Identity:
    return Identity(sub="someone", name="Someone", roles=frozenset(roles))


def _write(tmp_path: Path, content: object) -> Path:
    path = tmp_path / "permissions.yaml"
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return path


def test_the_versioned_matrix_loads_and_only_names_realm_roles() -> None:
    matrix = load_matrix(MATRIX)
    assert matrix == PERMISSIONS
    for permission, roles in matrix.items():
        assert roles <= frozenset(ROLES), permission
        assert roles, f"{permission} grants nothing to nobody: say so on purpose or remove it"
        assert "." in permission, permission


def test_a_role_that_is_not_in_the_realm_is_a_start_up_error(tmp_path: Path) -> None:
    path = _write(tmp_path, {"systems.read": ["the_boss"]})
    with pytest.raises(AuthzError, match="the_boss"):
        load_matrix(path)


def test_a_permission_without_roles_is_a_start_up_error(tmp_path: Path) -> None:
    path = _write(tmp_path, {"systems.read": []})
    with pytest.raises(AuthzError, match="systems.read"):
        load_matrix(path)


def test_asking_for_a_permission_the_matrix_does_not_declare_fails_at_start_up() -> None:
    with pytest.raises(AuthzError, match="campaigns.destroy"):
        require_perm("campaigns.destroy")


def test_the_guard_lets_through_only_the_roles_of_its_permission() -> None:
    guard = require_perm("campaigns.create")
    assert isinstance(guard, PermissionGuard)
    assert guard.permission == "campaigns.create"

    identity = _identity("campaign_manager")
    assert guard(identity) is identity

    with pytest.raises(HTTPException) as refused:
        guard(_identity("read_only_auditor"))
    assert refused.value.status_code == 403
    assert "campaigns.create" in str(refused.value.detail)


def test_holding_several_roles_is_enough_with_one_of_them() -> None:
    guard = require_perm("campaigns.approve")
    assert guard(_identity("read_only_auditor", "dpo_reviewer")).roles
