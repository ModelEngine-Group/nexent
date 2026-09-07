"""Unit tests for the role-based permission cache."""

import permissions.rbac as rbac
import pytest


@pytest.fixture(autouse=True)
def reset_cache():
    rbac._ROLE_PERMISSIONS.clear()
    rbac._INITIALIZED = False
    yield
    rbac._ROLE_PERMISSIONS.clear()
    rbac._INITIALIZED = False


def _records():
    return [
        {
            "user_role": "USER",
            "permission_category": "RESOURCE",
            "permission_type": "KB",
            "permission_subtype": "CREATE",
        },
        {
            "user_role": "ADMIN",
            "permission_category": "RESOURCE",
            "permission_type": "KB.CAPACITY",
            "permission_subtype": "READ",
        },
        {
            "user_role": "SU",
            "permission_category": "RESOURCE",
            "permission_type": "KB.CAPACITY",
            "permission_subtype": "MANAGE",
        },
    ]


def test_init_loads_lowercase_permissions(mocker):
    mocker.patch("permissions.rbac.get_all_role_permissions", return_value=_records())
    rbac.init_rbac()
    assert rbac.has_permission("USER", "kb:create")
    assert rbac.has_permission("admin", "kb.capacity:read")
    assert rbac.has_permission("SU", "kb.capacity:manage")


def test_has_permission_is_case_insensitive(mocker):
    mocker.patch("permissions.rbac.get_all_role_permissions", return_value=_records())
    rbac.init_rbac()
    assert rbac.has_permission("user", "KB:CREATE")
    assert rbac.has_permission("User", "kb:Create")


def test_missing_permission_returns_false(mocker):
    mocker.patch("permissions.rbac.get_all_role_permissions", return_value=_records())
    rbac.init_rbac()
    assert not rbac.has_permission("USER", "kb:delete")
    assert not rbac.has_permission("DEV", "kb:create")
    assert not rbac.has_permission(None, "kb:create")
    assert not rbac.has_permission("USER", "")


def test_non_resource_permissions_are_not_cached(mocker):
    records = _records() + [
        {
            "user_role": "USER",
            "permission_category": "VISIBILITY",
            "permission_type": "LEFT_NAV_MENU",
            "permission_subtype": "/knowledges",
        }
    ]
    mocker.patch("permissions.rbac.get_all_role_permissions", return_value=records)
    rbac.init_rbac()
    assert "left_nav_menu:/knowledges" not in rbac.get_role_permissions("USER")


def test_lazy_load_on_first_check(mocker):
    mock_load = mocker.patch("permissions.rbac.init_rbac")
    assert not rbac.has_permission("USER", "kb:create")
    mock_load.assert_called_once()


def test_init_failure_resets_initialized(mocker):
    mocker.patch(
        "permissions.rbac.get_all_role_permissions",
        side_effect=RuntimeError("db down"),
    )
    rbac.init_rbac()
    assert not rbac._INITIALIZED
