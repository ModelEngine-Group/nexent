# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tests for FastAPI authentication and permission dependencies."""

import gateway.authentication.auth as depends_dependencies
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import permissions.depends as depends


def test_authenticate_uses_authorization_header(mocker, monkeypatch):
    mocker.patch(
        "gateway.authentication.auth.get_current_user_context",
        return_value=("user-1", "tenant-1", "USER"),
    )

    current_user = depends_dependencies.authenticate("Bearer token", None)

    assert current_user.user_id == "user-1"
    assert current_user.tenant_id == "tenant-1"
    assert current_user.normalized_role == "USER"


def test_authenticate_uses_bearer_credentials_when_header_is_missing(mocker, monkeypatch):
    get_context = mocker.patch(
        "gateway.authentication.auth.get_current_user_context",
        return_value=("user-1", "tenant-1", "DEV"),
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="token"
    )

    current_user = depends_dependencies.authenticate(None, credentials)

    get_context.assert_called_once_with("token")
    assert current_user.normalized_role == "DEV"


def test_authenticate_rejects_missing_token_outside_speed_mode(monkeypatch):

    with pytest.raises(HTTPException) as raised:
        depends_dependencies.authenticate(None, None)

    assert raised.value.status_code == 401


def test_authenticate_does_not_restore_retired_anonymous_identity(mocker):
    get_context = mocker.patch("gateway.authentication.auth.get_current_user_context")
    with pytest.raises(HTTPException) as error:
        depends_dependencies.authenticate(None, None)
    assert error.value.status_code == 401
    get_context.assert_not_called()


def test_require_returns_user_when_permission_exists(mocker, monkeypatch):
    mocker.patch("permissions.depends.has_permission", return_value=True)
    current_user = depends.CurrentUser("user-1", "tenant-1", "ADMIN")

    result = depends.require("kb.capacity:read")(current_user)

    assert result is current_user


def test_require_rejects_missing_permission(mocker, monkeypatch):
    mocker.patch("permissions.depends.has_permission", return_value=False)
    current_user = depends.CurrentUser("user-1", "tenant-1", "USER")

    with pytest.raises(HTTPException) as raised:
        depends.require("kb.capacity:manage")(current_user)

    assert raised.value.status_code == 403
    assert "kb.capacity:manage" in raised.value.detail


def test_retired_role_has_no_permission_bypass(mocker):
    check = mocker.patch("permissions.depends.has_permission", return_value=False)
    with pytest.raises(HTTPException) as error:
        depends.require("kb.capacity:read")(depends.CurrentUser("retired", "tenant-1", "SPEED"))
    assert error.value.status_code == 403
    check.assert_called_once_with((), "kb.capacity:read")


def test_user_model_read_grant_does_not_authorize_model_writes(mocker, monkeypatch):
    from permissions import rbac

    monkeypatch.setattr(rbac, "_INITIALIZED", False)
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {})
    mocker.patch("permissions.rbac.get_all_role_permissions", return_value=[{
        "user_role": "USER",
        "permission_category": "RESOURCE",
        "permission_type": "MODEL",
        "permission_subtype": "READ",
    }])
    current_user = depends.CurrentUser("user-1", "tenant-1", "USER")

    assert depends.require("model:read")(current_user) is current_user
    for operation in ("create", "update", "delete"):
        with pytest.raises(HTTPException) as raised:
            depends.require(f"model:{operation}")(current_user)
        assert raised.value.status_code == 403
        assert raised.value.detail == f"Missing required permission: model:{operation}"
