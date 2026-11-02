# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Internal write boundaries share identifier validation before side effects."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from contracts.agent import AgentInfoRequest, ExportAndImportAgentInfo, ExportAndImportDataFormat
from contracts.authentication import AuthenticatedIdentity
from tool_collection.mcp.nl2agent_mcp_tools import AgentDraftFields


@pytest.mark.parametrize("name", ["agent_one", "中文助手", "a" * 100])
def test_internal_request_contract_preserves_legal_names(name):
    assert AgentInfoRequest(name=name).name == name
    assert AgentDraftFields(name=name).name == name


@pytest.mark.parametrize("name", ["class", "None", "agent-one", "9agent", " with_space", "", "a" * 101])
def test_save_request_rejects_invalid_names(name):
    with pytest.raises(ValidationError, match="Python identifier"):
        AgentInfoRequest(name=name)


def test_partial_draft_can_omit_or_clear_unassigned_name():
    assert AgentInfoRequest(description="partial").name is None
    assert AgentInfoRequest(name=None).name is None


@pytest.mark.parametrize("name", ["class", "agent-one", "a" * 101])
@pytest.mark.parametrize("entry", ["plain", "with_skills", "child"])
@pytest.mark.asyncio
async def test_import_rejects_invalid_name_before_loading_dependencies(mocker, name, entry):
    from management.services.agent import transfer

    agent = ExportAndImportAgentInfo(
        agent_id=1, name=name, description="test", max_steps=3,
        provide_run_summary=False, enabled=True, tools=[], managed_agents=[],
    )
    bundle = ExportAndImportDataFormat(agent_id=1, agent_info={"1": agent}, mcp_info=[])
    identity = AuthenticatedIdentity(user_id="owner", tenant_id="tenant", language="en")
    tools = mocker.patch.object(transfer, "query_all_tools")
    writes = mocker.patch.object(transfer, "create_agent")
    skills = mocker.patch.object(transfer.skill_db, "list_skills")
    with pytest.raises(ValueError, match="Python identifier"):
        if entry == "child":
            await transfer.import_agent_by_agent_id(agent, "tenant", "owner")
        elif entry == "with_skills":
            await transfer.import_agent_with_skills_impl(bundle, [], identity)
        else:
            await transfer.import_agent_impl(bundle, identity)
    tools.assert_not_called()
    writes.assert_not_called()
    skills.assert_not_called()


@pytest.mark.parametrize("name", ["class", "agent-one", "a" * 101])
@pytest.mark.parametrize("is_a2a", [False, True])
def test_publish_rejects_invalid_internal_name_before_snapshot(mocker, name, is_a2a):
    from management.services.agent import versions

    mocker.patch.object(versions, "is_system_agent", return_value=False)
    mocker.patch.object(versions, "query_agent_draft", return_value=({"name": name, "is_a2a": is_a2a}, [], []))
    writes = [mocker.patch.object(versions, key) for key in (
        "get_next_version_no", "insert_agent_snapshot", "insert_version", "update_agent_current_version",
    )]
    with pytest.raises(ValueError, match="Python identifier"):
        versions.publish_version_impl(1, "tenant", "owner")
    for write in writes:
        write.assert_not_called()


def test_duplicate_suffix_keeps_maximum_length_name_valid():
    from management.services.agent.naming import generate_unique_agent_value

    name = generate_unique_agent_value("name", "a" * 100, "tenant", agents_cache=[])
    assert len(name) == 100
    assert name.endswith("_1")
    assert AgentInfoRequest(name=name).name == name


def test_regeneration_retries_invalid_model_output(mocker):
    from management.services.agent import naming

    mocker.patch.object(naming, "load_default_generation_prompt", return_value={})
    mocker.patch.object(naming, "compose_name_regeneration", return_value=SimpleNamespace(user="u", system="s"))
    model = mocker.patch.object(naming, "call_llm_for_system_prompt", side_effect=["class", "bad-name", "中文助手"])
    assert naming.regenerate_agent_value("name", "original", [], "task", 1, "tenant", agents_cache=[]) == "中文助手"
    assert model.call_count == 3


@pytest.mark.parametrize("name,valid", [
    ("中文助手", True), ("a" * 100, True), ("class", False), ("bad-name", False), ("a" * 101, False),
])
@pytest.mark.asyncio
async def test_generation_completion_uses_the_same_identifier_contract(mocker, name, valid):
    from services import nl2agent_service as service

    draft = {
        "name": name, "description": "Ready", "prompt": "Ready", "greeting_message": "Hello",
        "example_questions": ["Help"],
    }
    mocker.patch.object(service, "_load_verified_nl2agent_state", return_value=(draft, {}))
    if valid:
        assert await service.validate_agent_generation_complete_impl(
            agent_id=1, tenant_id="tenant", user_id="owner",
        ) is None
    else:
        with pytest.raises(service.Nl2AgentCompletionError, match="draft_fields_incomplete"):
            await service.validate_agent_generation_complete_impl(agent_id=1, tenant_id="tenant", user_id="owner")
