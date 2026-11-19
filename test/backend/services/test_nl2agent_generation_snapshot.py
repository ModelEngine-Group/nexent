# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Generation facts and their revision share one set of binding reads."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from services import nl2agent_prompt_service as prompts
from services import nl2agent_service as service
from services.nl2agent_state_service import ResourceScope
from tool_collection.mcp import nl2agent_resource_tools as tools


@pytest.fixture
def bindings(mocker):
    scope = ResourceScope("tenant", "user", 42, "7", "run")
    tool_rows = [{"tool_instance_id": 1, "tool_id": 7, "params": {"token": "tool-secret"}}]
    skill_rows = [{"skill_instance_id": 2, "skill_id": 11, "config_values": {"token": "skill-secret"},
                   "config_schemas": [{"name": "token", "required": True}]}]
    authorize = mocker.patch.object(service, "require_agent_draft_edit", return_value={"prompt": "Saved"})
    mocker.patch.object(service, "_load_installed_resource_catalog", new=AsyncMock(return_value=[
        {"candidate_ref": "tool:7", "name": "lookup", "description": "Search", "inputs": {}, "config": []},
        {"candidate_ref": "skill:11", "name": "report", "description": "Report", "inputs": {}, "config": []},
    ]))
    read_tools = mocker.patch.object(service, "query_all_enabled_tool_instances",
                                    side_effect=lambda **kwargs: deepcopy(tool_rows))
    read_skills = mocker.patch.object(service, "query_enabled_skill_instances",
                                     side_effect=lambda **kwargs: deepcopy(skill_rows))
    stored = {}

    async def update(key, change):
        stored[key.key] = change(stored.get(key.key))
        return stored[key.key]

    mocker.patch.object(prompts, "update_resource_state", side_effect=update)
    mocker.patch.object(prompts, "read_resource_state", new=AsyncMock(return_value=None))
    return scope, tool_rows, skill_rows, read_tools, read_skills, authorize, stored


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["snapshot", "context"])
async def test_one_read_per_binding_kind_and_no_private_model_data(bindings, entry):
    scope, tool_rows, skill_rows, read_tools, read_skills, _, stored = bindings
    if entry == "snapshot":
        basis = await prompts.snapshot(scope)
        facts = [
            {"resource_type": "skill", "resource_id": 11, "name": "report", "description": "Report", "runtime_inputs": []},
            {"resource_type": "tool", "resource_id": 7, "name": "lookup", "description": "Search", "runtime_inputs": []},
        ]
    else:
        context = await tools._read_generation_context(scope)
        facts = context["bound_resources"]
        basis = stored[prompts._key(scope, "run:" + scope.run_id).key]
        assert "binding_revision" not in context
        assert "tool-secret" not in json.dumps(context)
        assert "skill-secret" not in json.dumps(context)
    expected = prompts.revision({"facts": facts, "instances": [
        ["skill", 2, 11, skill_rows[0]["config_values"], skill_rows[0]["config_schemas"]],
        ["tool", 1, 7, tool_rows[0]["params"]],
    ]})
    assert basis["prompt"] == "Saved"
    assert basis["bindings"] == expected
    for reader in (read_tools, read_skills):
        reader.assert_called_once_with(agent_id=42, tenant_id="tenant", version_no=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["tool_config", "skill_config", "skill_schema", "unbind", "empty"])
async def test_each_later_snapshot_detects_binding_changes(bindings, change):
    scope, tool_rows, skill_rows, read_tools, read_skills, _, _ = bindings
    original = await prompts.snapshot(scope)
    if change == "tool_config":
        tool_rows[0]["params"]["token"] = "changed"
    elif change == "skill_config":
        skill_rows[0]["config_values"]["token"] = "changed"
    elif change == "skill_schema":
        skill_rows[0]["config_schemas"][0]["required"] = False
    elif change == "unbind":
        tool_rows.clear()
    else:
        tool_rows.clear()
        skill_rows.clear()
    assert (await prompts.snapshot(scope))["bindings"] != original["bindings"]
    assert read_tools.call_count == read_skills.call_count == 2


@pytest.mark.asyncio
async def test_empty_bindings_have_stable_revision_and_default_state_has_no_digest(bindings):
    scope, tool_rows, skill_rows, _, _, _, _ = bindings
    tool_rows.clear()
    skill_rows.clear()
    first = await prompts.snapshot(scope)
    assert await prompts.snapshot(scope) == first
    state = await service.read_generation_state(agent_id=42, tenant_id="tenant", user_id="user")
    assert state["bound_resources"] == []
    assert "binding_revision" not in state


@pytest.mark.asyncio
async def test_unready_bindings_remain_in_revision_without_entering_facts(bindings, mocker):
    scope, tool_rows, _, _, _, _, stored = bindings
    mocker.patch.object(service, "_bound_config_ready", return_value=False)
    context = await tools._read_generation_context(scope)
    assert context["bound_resources"] == []
    first = stored[prompts._key(scope, "run:" + scope.run_id).key]["bindings"]
    tool_rows[0]["params"]["token"] = "changed"
    assert (await prompts.snapshot(scope))["bindings"] != first


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["permission", "tools", "skills"])
async def test_failed_snapshot_propagates_error_without_recording_basis(bindings, failure):
    scope, _, _, read_tools, read_skills, authorize, stored = bindings
    failing = {"permission": authorize, "tools": read_tools, "skills": read_skills}[failure]
    failing.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        await tools._read_generation_context(scope)
    assert stored == {}
    if failure == "permission":
        read_tools.assert_not_called()
        read_skills.assert_not_called()
