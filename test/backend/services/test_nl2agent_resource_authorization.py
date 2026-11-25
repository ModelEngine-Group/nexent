# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current user visibility is enforced before search and candidate disclosure."""

from unittest.mock import AsyncMock

import pytest

from management.services.agent import nl2agent as service
from services import nl2agent_resource_flow as flow
from services.nl2agent_state_service import ResourceScope, ResourceStateError


@pytest.fixture
def sources(mocker):
    async def inline(_name, fn, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return fn(*args, **kwargs)
    mocker.patch.object(service, "run_blocking", side_effect=inline)
    tools = [{"tool_id": i, "name": f"search_{i}", "description": "Search", "source": "mcp",
              "is_available": True, "usage": name, "params": [], "inputs": {}}
             for i, name in enumerate(["shared", "private-a", "private-b", "disabled"], 1)]
    mocker.patch("management.services.tool.configuration.list_all_tools", new=AsyncMock(return_value=tools))
    mocker.patch("management.services.skill.service.SkillService.list_visible_skills", return_value=[])
    from management.services.mcp import service as mcp
    mocker.patch.object(mcp, "get_mcp_records_by_tenant", return_value=[
        {"mcp_name": "shared", "enabled": True, "group_ids": None},
        {"mcp_name": "private-a", "enabled": True, "group_ids": "", "created_by": "a"},
        {"mcp_name": "private-b", "enabled": True, "group_ids": "", "created_by": "b"},
        {"mcp_name": "disabled", "enabled": False, "group_ids": None},
    ])
    groups = mocker.patch.object(mcp, "query_group_ids_by_user", return_value=[])
    return groups


async def test_private_mcp_tools_are_user_scoped_before_retrieval(sources):
    a = await service._load_installed_resource_catalog(tenant_id="tenant", user_id="a")
    b = await service._load_installed_resource_catalog(tenant_id="tenant", user_id="b")
    assert {r["candidate_ref"] for r in a} == {"tool:1", "tool:2"}
    assert {r["candidate_ref"] for r in b} == {"tool:1", "tool:3"}


async def test_permission_lookup_failure_never_uses_tenant_catalog(sources):
    sources.side_effect = RuntimeError("permissions unavailable")
    with pytest.raises(RuntimeError, match="permissions unavailable"):
        await service._load_installed_resource_catalog(tenant_id="tenant", user_id="a")


async def test_repository_permission_failure_is_not_converted_to_public_scope(mocker):
    from management.services.repository.mcp import service as repository
    mocker.patch.object(repository, "_get_user_role", return_value="USER")
    mocker.patch.object(repository, "query_group_ids_by_user", side_effect=RuntimeError("groups unavailable"))
    listings = mocker.patch.object(repository, "get_mcp_market_records")
    with pytest.raises(RuntimeError, match="groups unavailable"):
        await repository.list_community_mcp_services(
            tenant_id="tenant", user_id="a", strict_permissions=True)
    listings.assert_not_called()


async def test_anonymous_discovery_is_rejected(sources):
    with pytest.raises(ValueError, match="authenticated"):
        await service._load_installed_resource_catalog(tenant_id="tenant", user_id="")


async def test_cached_batch_is_reauthorized_before_disclosure(mocker):
    scope = ResourceScope("tenant", "a", 1, "c", "r")
    candidate = {"candidate_ref": "tool:private", "resource_type": "tool", "source": "MCP_TOOL",
                 "name": "private", "description": "Private capability", "retrieval_score": .8,
                 "capability_evidence": "installed_declaration"}
    state = {"requirements": {"r1": {"query": "search", "installed": [candidate], "installable": []}},
             "batch": {"id": "b1", "requirements": ["r1"]}}
    mocker.patch.object(service, "_load_installed_resource_catalog", return_value=[])
    with pytest.raises(ResourceStateError, match="resource_evidence_changed"):
        await flow._authorized_batch_result(scope, state)


async def test_cached_batch_rejects_changed_alias_or_capability_text(mocker):
    from services import nl2agent_semantic_retrieval as semantic
    scope = ResourceScope("tenant", "a", 1, "c", "r")
    resource = {"candidate_ref": "tool:1", "resource_type": "tool", "source": "LOCAL_TOOL",
                "name": "search", "description": "Search", "installed": True, "descriptions": ["Old capability"]}
    candidate = flow._candidate(resource, .8)
    state = {"requirements": {"r1": {"query": "search", "installed": [candidate], "installable": [],
        "resource_revisions": {"tool:1": semantic.resource_revision(resource)}}},
        "batch": {"id": "b1", "requirements": ["r1"]}}
    mocker.patch.object(service, "_load_installed_resource_catalog",
                      return_value=[{**resource, "descriptions": ["Changed capability"]}])
    with pytest.raises(ResourceStateError, match="resource_evidence_changed"):
        await flow._authorized_batch_result(scope, state)
