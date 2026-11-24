# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise NL2Agent repository pagination without external catalog dependencies."""

import pytest

from management.services.agent import nl2agent as nl2agent_service


@pytest.fixture
def repository_pages(mocker):
    mocker.patch("management.services.skill.transfer.get_official_skills_with_status", return_value=[])
    skill_pages = mocker.patch("management.services.skill.skill_repository.list_skill_repository_listings_impl")
    mcp_pages = mocker.patch("management.services.repository.mcp.service.list_community_mcp_services")
    return skill_pages, mcp_pages


async def test_resource_catalog_follows_next_page_even_if_current_page_is_empty(repository_pages):
    skill_pages, mcp_pages = repository_pages
    skill_pages.side_effect = [
        {"items": [], "pagination": {"total_pages": 2}},
        {"items": [{"id": 5, "name": "late skill"}], "pagination": {"total_pages": 2}},
    ]
    mcp_pages.side_effect = [
        {"items": [], "nextCursor": "page-2"},
        {"items": [{"marketId": 9, "name": "late MCP", "serverUrl": "https://fixture.invalid/mcp"}],
         "nextCursor": None},
    ]

    catalog = await nl2agent_service._load_internal_uninstalled_resource_catalog(
        tenant_id="tenant-a", user_id="user-a",
    )

    assert [item["candidate_ref"] for item in catalog] == ["tenant_skill_repository:5", "tenant_mcp_repository:9"]
    assert [call.kwargs["page"] for call in skill_pages.call_args_list] == [1, 2]
    assert [call.kwargs["cursor"] for call in mcp_pages.await_args_list] == [None, "page-2"]


async def test_resource_catalog_rejects_a_cursor_cycle(repository_pages):
    skill_pages, mcp_pages = repository_pages
    skill_pages.return_value = {"items": [], "pagination": {"total_pages": 0}}
    mcp_pages.side_effect = [
        {"items": [], "nextCursor": "a"},
        {"items": [], "nextCursor": "b"},
        {"items": [], "nextCursor": "a"},
    ]

    with pytest.raises(ValueError, match="MCP repository cursor"):
        await nl2agent_service._load_internal_uninstalled_resource_catalog(tenant_id="tenant-a", user_id="user-a")

    assert [call.kwargs["cursor"] for call in mcp_pages.await_args_list] == [None, "a", "b"]
