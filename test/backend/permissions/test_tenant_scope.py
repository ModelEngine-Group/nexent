"""Tests for tenant-scope authorization helpers."""

import pytest
from fastapi import HTTPException
from permissions.models import CurrentUser
from permissions.tenant_scope import resolve_personal_target_tenant


def _user(role: str = "ADMIN", tenant_id: str = "tenant-a") -> CurrentUser:
    return CurrentUser(
        user_id="user-1",
        tenant_id=tenant_id,
        role=role,
    )


def test_defaults_to_current_tenant():
    assert resolve_personal_target_tenant(_user(), None) == "tenant-a"


def test_regular_role_cannot_select_another_tenant():
    with pytest.raises(HTTPException) as raised:
        resolve_personal_target_tenant(_user(), "tenant-b")

    assert raised.value.status_code == 403
    assert "another tenant" in str(raised.value.detail)


@pytest.mark.parametrize("role", ["SU", "SPEED"])
def test_cross_tenant_roles_can_select_another_tenant(role: str):
    assert resolve_personal_target_tenant(_user(role=role), "tenant-b") == "tenant-b"
