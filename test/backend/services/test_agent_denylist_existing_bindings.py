# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace

import pytest

from contracts.authentication import AuthenticatedIdentity
from contracts.errors.exceptions import ResourceBindingError
from management.services.agent import service
from management.services.configuration import resource_denylist as denylist


@pytest.fixture
def save_context(mocker):
    mocker.patch.object(service, "is_system_agent", return_value=False)
    mocker.patch.object(service, "_validate_agent_relationships", return_value=None)
    mocker.patch.object(service, "_normalize_agent_output_reserve")
    mocker.patch.object(service, "search_agent_info_by_agent_id", return_value={})
    mocker.patch.object(service, "get_user_tenant_by_user_id", return_value={})
    mocker.patch.object(service, "roles_from_record", return_value=["ADMIN"])
    mocker.patch.object(service, "resolve_agent_list_permission", return_value="EDIT")
    mocker.patch.object(service, "build_reasoning_snapshot", return_value={})
    update = mocker.patch.object(service, "update_agent")
    write_skill = mocker.patch.object(service.skill_db, "create_or_update_skill_by_skill_info")
    mocker.patch.object(service.skill_db, "query_skill_instances_by_agent_id", return_value=[
        {"skill_id": 1, "enabled": True, "config_values": {}},
    ])
    mocker.patch.object(service.skill_db, "get_valid_skill_ids", return_value={1, 2})
    mocker.patch.object(service.skill_db, "query_skill_names_by_ids", return_value=[{"skill_id": 2, "name": "blocked"}])
    read_policy = mocker.patch.object(denylist, "load_tool_denylist", return_value=denylist.ToolDenylist(
        frozenset(), frozenset({"skill:2"}),
    ))
    request = SimpleNamespace(agent_id=7, example_questions=None, related_external_agent_ids=None,
                              model_fields_set=set(), model_params_override=None, enabled_tool_ids=None,
                              enabled_skill_ids=[2], skill_instances=None, version_no=0)
    return request, update, write_skill, read_policy


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("scope", ["tenant", "global"])
async def test_blocked_new_skill_is_rejected_before_agent_or_existing_binding_writes(save_context, structured, scope):
    request, update, write_skill, policy = save_context
    if structured:
        request.skill_instances = [SimpleNamespace(skill_id=2, enabled=True, config_values={})]
    if scope == "global":
        policy.return_value = denylist.ToolDenylist(frozenset(), frozenset(), frozenset({"skill:blocked"}))
    with pytest.raises(ResourceBindingError, match="resource_blocked"):
        await service.update_agent_info_impl(request, AuthenticatedIdentity("review-user", "review-tenant"))
    update.assert_not_called()
    write_skill.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_existing_blocked_skill_can_be_retained_and_configured(save_context, structured):
    request, update, write_skill, policy = save_context
    policy.return_value = denylist.ToolDenylist(frozenset(), frozenset({"skill:1"}))
    request.enabled_skill_ids = [1]
    if structured:
        request.skill_instances = [SimpleNamespace(skill_id=1, enabled=True, config_values={"query": "new value"})]
    assert await service.update_agent_info_impl(request, AuthenticatedIdentity("user", "tenant")) == {"agent_id": 7}
    update.assert_called_once()
    write_skill.assert_called_once()
    assert write_skill.call_args.kwargs["skill_info"].enabled
    if structured:
        assert write_skill.call_args.kwargs["skill_info"].config_values == {"query": "new value"}
    policy.assert_not_called()


@pytest.mark.asyncio
async def test_existing_blocked_skill_can_be_removed(save_context):
    request, update, write_skill, policy = save_context
    request.enabled_skill_ids = []
    await service.update_agent_info_impl(request, AuthenticatedIdentity("user", "tenant"))
    assert write_skill.call_args.kwargs["skill_info"].enabled is False
    policy.assert_not_called()
