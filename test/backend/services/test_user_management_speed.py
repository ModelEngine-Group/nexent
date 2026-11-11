# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Speed-mode identity and permission regression contracts."""

from unittest.mock import MagicMock, patch

from management.services.permission.identity.authentication import get_user_info


@patch("management.services.permission.identity.authentication.as_dict")
@patch("management.services.permission.identity.authentication.format_role_permissions")
@patch("management.services.permission.identity.authentication.get_db_session")
@patch("management.services.permission.identity.authentication.get_user_tenant_by_user_id")
@patch("management.services.permission.identity.authentication.query_group_ids_by_user")
@patch("management.services.permission.identity.authentication.IS_SPEED_MODE", True)
async def test_speed_mode_uses_speed_permissions_for_disabled_system_account(
    mock_query_group_ids,
    mock_get_user_tenant,
    mock_get_db_session,
    mock_format_permissions,
    mock_as_dict,
):
    """The disabled login identity must not hide the speed-mode demo permissions."""
    mock_get_user_tenant.return_value = {
        "tenant_id": "tenant_id",
        "user_role": None,
        "user_email": None,
    }
    mock_query_group_ids.return_value = []

    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.all.return_value = [MagicMock()]
    mock_get_db_session.return_value.__enter__.return_value = mock_session
    mock_get_db_session.return_value.__exit__.return_value = None
    mock_as_dict.return_value = {
        "permission_category": "VISIBILITY",
        "permission_type": "LEFT_NAV_MENU",
        "permission_subtype": "/newchat",
    }
    mock_format_permissions.return_value = {
        "permissions": [],
        "accessibleRoutes": ["/newchat"],
    }

    result = await get_user_info("user_id")

    assert result is not None
    assert result["user"]["user_role"] == "SPEED"
    assert result["user"]["accessibleRoutes"] == ["/newchat"]
    role_filter = mock_query.filter.call_args.args[0]
    assert role_filter.right.value == "SPEED"
