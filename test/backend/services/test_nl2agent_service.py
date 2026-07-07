"""Unit tests for NL2AGENT service orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services import nl2agent_service


class _FixedUuid:
    hex = "abcdef1234567890"


@pytest.mark.asyncio
async def test_start_session_returns_builder_draft_and_conversation_ids(monkeypatch):
    search_builder = MagicMock(return_value=101)
    search_agent = MagicMock(
        return_value={
            "agent_id": 101,
            "prompt_template_id": 0,
            "prompt_template_name": "system_default",
        }
    )
    create_draft = MagicMock(return_value={"agent_id": 202})
    create_conversation = MagicMock(return_value={"conversation_id": 303})

    monkeypatch.setattr(
        nl2agent_service, "search_agent_id_by_agent_name", search_builder
    )
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", search_agent)
    monkeypatch.setattr(nl2agent_service, "create_agent", create_draft)
    monkeypatch.setattr(
        nl2agent_service, "create_conversation", create_conversation
    )
    monkeypatch.setattr(
        nl2agent_service.uuid, "uuid4", MagicMock(return_value=_FixedUuid())
    )

    result = await nl2agent_service.start_session(
        user_id="user_1", tenant_id="tenant_1", language="en"
    )

    assert result == {
        "nl2agent_agent_id": 101,
        "draft_agent_id": 202,
        "conversation_id": 303,
        "draft_name": "draft_abcdef12",
    }
    assert result["draft_agent_id"] != result["nl2agent_agent_id"]

    search_builder.assert_called_once_with("nl2agent", "tenant_1")
    search_agent.assert_called_once_with(agent_id=101, tenant_id="tenant_1")
    draft_payload = create_draft.call_args.args[0]
    assert draft_payload["name"] == "draft_abcdef12"
    assert draft_payload["name"].startswith("draft_")
    create_draft.assert_called_once_with(
        draft_payload, tenant_id="tenant_1", user_id="user_1"
    )
    create_conversation.assert_called_once_with(
        conversation_title="NL2AGENT - draft_abcdef12", user_id="user_1"
    )


@pytest.mark.asyncio
async def test_start_session_seeds_nl2agent_for_current_tenant_when_missing(
    monkeypatch,
):
    search_builder = MagicMock(side_effect=Exception("agent not found"))
    seed_builder = MagicMock(return_value=101)
    search_agent = MagicMock(
        return_value={
            "agent_id": 101,
            "prompt_template_id": 0,
            "prompt_template_name": "system_default",
        }
    )
    create_draft = MagicMock(return_value={"agent_id": 202})
    create_conversation = MagicMock(return_value={"conversation_id": 303})

    monkeypatch.setattr(
        nl2agent_service, "search_agent_id_by_agent_name", search_builder
    )
    monkeypatch.setattr(
        nl2agent_service, "seed_nl2agent_default_agent", seed_builder
    )
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", search_agent)
    monkeypatch.setattr(nl2agent_service, "create_agent", create_draft)
    monkeypatch.setattr(
        nl2agent_service, "create_conversation", create_conversation
    )
    monkeypatch.setattr(
        nl2agent_service.uuid, "uuid4", MagicMock(return_value=_FixedUuid())
    )

    result = await nl2agent_service.start_session(
        user_id="user_1", tenant_id="tenant_1", language="en"
    )

    assert result["nl2agent_agent_id"] == 101
    assert result["draft_agent_id"] == 202
    search_builder.assert_called_once_with("nl2agent", "tenant_1")
    seed_builder.assert_called_once_with(tenant_id="tenant_1", user_id="user_1")
    search_agent.assert_called_once_with(agent_id=101, tenant_id="tenant_1")
    draft_payload = create_draft.call_args.args[0]
    assert draft_payload["name"] == "draft_abcdef12"


@pytest.mark.asyncio
async def test_start_session_backfills_existing_nl2agent_prompt_template_link(
    monkeypatch,
):
    search_builder = MagicMock(return_value=101)
    search_agent = MagicMock(
        return_value={
            "agent_id": 101,
            "prompt_template_id": None,
            "prompt_template_name": None,
        }
    )
    update_agent = MagicMock()
    create_draft = MagicMock(return_value={"agent_id": 202})
    create_conversation = MagicMock(return_value={"conversation_id": 303})

    monkeypatch.setattr(
        nl2agent_service, "search_agent_id_by_agent_name", search_builder
    )
    monkeypatch.setattr(nl2agent_service, "search_agent_info_by_agent_id", search_agent)
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)
    monkeypatch.setattr(nl2agent_service, "create_agent", create_draft)
    monkeypatch.setattr(
        nl2agent_service, "create_conversation", create_conversation
    )
    monkeypatch.setattr(
        nl2agent_service.uuid, "uuid4", MagicMock(return_value=_FixedUuid())
    )

    result = await nl2agent_service.start_session(
        user_id="user_1", tenant_id="tenant_1", language="en"
    )

    assert result["nl2agent_agent_id"] == 101
    request = update_agent.call_args.kwargs["agent_info"]
    assert request.prompt_template_id == 0
    assert request.prompt_template_name == "system_default"
    update_agent.assert_called_once_with(
        agent_id=101,
        agent_info=request,
        user_id="user_1",
        version_no=0,
    )


@pytest.mark.asyncio
async def test_recommend_local_resources_awaits_tool_list_and_filters_sources(monkeypatch):
    list_tools = AsyncMock(
        return_value=[
            {"tool_id": 1, "name": "local_tool", "source": "local"},
            {"tool_id": 2, "name": "mcp_tool", "source": "mcp"},
            {"tool_id": 3, "name": "langchain_tool", "source": "langchain"},
            {"tool_id": 4, "name": "nl2agent_builtin", "source": "builtin"},
            {"tool_id": 5, "name": "remote_tool", "source": "remote"},
        ]
    )
    list_skills = MagicMock(return_value=[])
    scored_candidates = {}

    def score_candidates(*, candidates, kind, **_kwargs):
        scored_candidates[kind] = candidates
        return candidates

    monkeypatch.setattr(nl2agent_service, "list_all_tools", list_tools)
    monkeypatch.setattr(nl2agent_service, "list_tenant_skills", list_skills)
    monkeypatch.setattr(
        nl2agent_service,
        "_score_candidates_with_llm",
        MagicMock(side_effect=score_candidates),
    )

    result = await nl2agent_service.recommend_local_resources(
        query="need database access",
        agent_id=202,
        tenant_id="tenant_1",
        model_id=9,
    )

    list_tools.assert_awaited_once_with(tenant_id="tenant_1", labels=None)
    list_skills.assert_called_once_with(tenant_id="tenant_1")
    assert {tool["source"] for tool in scored_candidates["tool"]} == {
        "local",
        "mcp",
        "langchain",
    }
    assert [tool["tool_id"] for tool in result["tools"]] == [1, 2, 3]
    assert result["skills"] == []


@pytest.mark.asyncio
async def test_apply_local_resources_batch_binds_tools_and_installed_skills_to_draft(
    monkeypatch,
):
    query_tools = MagicMock(return_value=[{"tool_id": 42, "params": {"path": "/tmp"}}])
    bind_tool = MagicMock()
    get_tenant_skill = MagicMock(return_value=None)
    install_skill = MagicMock(return_value=[107])
    bind_skill = MagicMock()

    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids", query_tools)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )
    monkeypatch.setattr(nl2agent_service, "get_tenant_skill_by_id", get_tenant_skill)
    monkeypatch.setattr(nl2agent_service, "install_skills_for_tenant", install_skill)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_skill_by_skill_info", bind_skill
    )

    result = await nl2agent_service.apply_local_resources_batch(
        agent_id=202,
        tool_ids=[42],
        skill_ids=[7],
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result == {
        "bound_tool_count": 1,
        "bound_skill_count": 1,
        "tool_ids": [42],
        "skill_ids": [107],
    }

    tool_request = bind_tool.call_args.kwargs["tool_info"]
    assert tool_request.tool_id == 42
    assert tool_request.agent_id == 202
    assert tool_request.params == {"path": "/tmp"}
    assert tool_request.enabled is True
    bind_tool.assert_called_once()

    get_tenant_skill.assert_called_once_with(7, "tenant_1")
    install_skill.assert_called_once_with(
        skill_ids=[7], tenant_id="tenant_1", user_id="user_1"
    )
    skill_request = bind_skill.call_args.kwargs["skill_info"]
    assert skill_request.skill_id == 107
    assert skill_request.agent_id == 202
    assert skill_request.enabled is True
    assert skill_request.version_no == 0
    bind_skill.assert_called_once()


def test_seed_nl2agent_default_agent_sets_prompt_template_link(monkeypatch):
    seed_tools = MagicMock(return_value=[11, 12])
    query_agents = MagicMock(return_value=[])
    create_agent = MagicMock(return_value={"agent_id": 101})
    bind_tool = MagicMock()

    monkeypatch.setattr(nl2agent_service, "seed_nl2agent_builtin_tools", seed_tools)
    monkeypatch.setattr(
        nl2agent_service, "query_all_agent_info_by_tenant_id", query_agents
    )
    monkeypatch.setattr(nl2agent_service, "create_agent", create_agent)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )

    result = nl2agent_service.seed_nl2agent_default_agent(
        tenant_id="tenant_1", user_id="user_1"
    )

    assert result == 101
    payload = create_agent.call_args.args[0]
    assert payload["name"] == "nl2agent"
    assert payload["prompt_template_id"] == 0
    assert payload["prompt_template_name"] == "system_default"


def test_seed_nl2agent_default_agent_backfills_existing_prompt_template_link(
    monkeypatch,
):
    seed_tools = MagicMock(return_value=[11, 12])
    query_agents = MagicMock(
        return_value=[
            {
                "agent_id": 101,
                "name": "nl2agent",
                "prompt_template_id": None,
                "prompt_template_name": None,
            }
        ]
    )
    update_agent = MagicMock()
    create_agent = MagicMock()

    monkeypatch.setattr(nl2agent_service, "seed_nl2agent_builtin_tools", seed_tools)
    monkeypatch.setattr(
        nl2agent_service, "query_all_agent_info_by_tenant_id", query_agents
    )
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)
    monkeypatch.setattr(nl2agent_service, "create_agent", create_agent)

    result = nl2agent_service.seed_nl2agent_default_agent(
        tenant_id="tenant_1", user_id="user_1"
    )

    assert result == 101
    create_agent.assert_not_called()
    request = update_agent.call_args.kwargs["agent_info"]
    assert request.prompt_template_id == 0
    assert request.prompt_template_name == "system_default"
    update_agent.assert_called_once_with(
        agent_id=101,
        agent_info=request,
        user_id="user_1",
        version_no=0,
    )
