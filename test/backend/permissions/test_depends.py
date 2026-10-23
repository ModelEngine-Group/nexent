"""Tests for FastAPI authentication and permission dependencies."""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from permissions import depends


def test_authenticate_uses_authorization_header(mocker, monkeypatch):
    monkeypatch.setattr(depends, "IS_SPEED_MODE", False)
    mocker.patch(
        "permissions.depends.get_current_user_context",
        return_value=("user-1", "tenant-1", "USER"),
    )

    current_user = depends.authenticate("Bearer token", None)

    assert current_user.user_id == "user-1"
    assert current_user.tenant_id == "tenant-1"
    assert current_user.normalized_role == "USER"


def test_authenticate_uses_bearer_credentials_when_header_is_missing(mocker, monkeypatch):
    monkeypatch.setattr(depends, "IS_SPEED_MODE", False)
    get_context = mocker.patch(
        "permissions.depends.get_current_user_context",
        return_value=("user-1", "tenant-1", "DEV"),
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="token"
    )

    current_user = depends.authenticate(None, credentials)

    get_context.assert_called_once_with("token")
    assert current_user.normalized_role == "DEV"


def test_authenticate_rejects_missing_token_outside_speed_mode(monkeypatch):
    monkeypatch.setattr(depends, "IS_SPEED_MODE", False)

    with pytest.raises(HTTPException) as raised:
        depends.authenticate(None, None)

    assert raised.value.status_code == 401


def test_authenticate_allows_missing_token_in_speed_mode(mocker, monkeypatch):
    monkeypatch.setattr(depends, "IS_SPEED_MODE", True)
    get_context = mocker.patch(
        "permissions.depends.get_current_user_context",
        return_value=("speed-user", "tenant-1", "SPEED"),
    )

    current_user = depends.authenticate(None, None)

    get_context.assert_called_once_with(None)
    assert current_user.normalized_role == "SPEED"


def test_require_returns_user_when_permission_exists(mocker, monkeypatch):
    monkeypatch.setattr(depends, "IS_SPEED_MODE", False)
    mocker.patch("permissions.depends.has_permission", return_value=True)
    current_user = depends.CurrentUser("user-1", "tenant-1", "ADMIN")

    result = depends.require("kb.capacity:read")(current_user)

    assert result is current_user


def test_require_rejects_missing_permission(mocker, monkeypatch):
    monkeypatch.setattr(depends, "IS_SPEED_MODE", False)
    mocker.patch("permissions.depends.has_permission", return_value=False)
    current_user = depends.CurrentUser("user-1", "tenant-1", "USER")

    with pytest.raises(HTTPException) as raised:
        depends.require("kb.capacity:manage")(current_user)

    assert raised.value.status_code == 403
    assert "kb.capacity:manage" in raised.value.detail


def test_require_bypasses_seeded_permission_for_speed_role(mocker, monkeypatch):
    monkeypatch.setattr(depends, "IS_SPEED_MODE", True)
    has_permission = mocker.patch(
        "permissions.depends.has_permission", return_value=False
    )
    current_user = depends.CurrentUser("speed-user", "tenant-1", "SPEED")

    assert depends.require("kb.capacity:read")(current_user) is current_user
    has_permission.assert_not_called()
