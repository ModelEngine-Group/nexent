# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""A retained marketplace origin does not imply that the resource is published."""

import pytest

from management.services.mcp import service


@pytest.mark.asyncio
@pytest.mark.parametrize("shared_ids,listed", [(set(), False), ({41}, True)])
async def test_mcp_list_preserves_origin_and_reports_actual_publication(mocker, shared_ids, listed):
    mocker.patch.object(service, "get_mcp_records_by_tenant", return_value=[{
        "mcp_id": 3, "mcp_name": "local", "mcp_server": "https://fixture.invalid",
        "source": "local", "market_id": 41, "created_by": "owner", "group_ids": None,
        "enabled": False, "tags": [],
    }])
    mocker.patch.object(service, "get_user_tenant_by_user_id", return_value={"user_role": "ADMIN"})
    mocker.patch.object(service, "query_group_ids_by_user", return_value=[])
    manager = mocker.patch.object(service, "MCPContainerManager")
    manager.return_value.list_mcp_containers.return_value = []
    lookup = mocker.patch("management.db.mcp.market.get_shared_mcp_market_ids", return_value=shared_ids)
    result = await service.get_remote_mcp_server_list(tenant_id="tenant", user_id="owner")
    assert result[0]["market_id"] == 41
    assert result[0]["is_listed_in_repository"] is listed
    lookup.assert_called_once_with([41])


@pytest.mark.asyncio
async def test_mcp_list_resolves_author_for_visible_records_only(mocker):
    def record(name, creator, groups=None):
        return {
            "mcp_name": name, "mcp_server": "https://fixture.invalid",
            "created_by": creator, "group_ids": groups,
        }

    mocker.patch.object(service, "get_mcp_records_by_tenant", return_value=[
        record("uploaded-image", "owner"),
        record("unknown-author", "deleted-user"),
        record("hidden", "other-user", "other-group"),
    ])
    mocker.patch.object(service, "get_user_tenant_by_user_id", return_value={})
    mocker.patch.object(service, "query_group_ids_by_user", return_value=[])
    manager = mocker.patch.object(service, "MCPContainerManager")
    manager.return_value.list_mcp_containers.return_value = []
    lookup = mocker.patch.object(
        service, "get_user_email_map", return_value={"owner": "owner@example.com"},
    )

    result = await service.get_remote_mcp_server_list(
        tenant_id="tenant", user_id="owner", include_author=True,
    )

    assert [row["remote_mcp_server_name"] for row in result] == ["uploaded-image", "unknown-author"]
    assert [row["author_display_name"] for row in result] == ["owner@example.com", None]
    assert set(lookup.call_args.args[0]) == {"owner", "deleted-user"}
