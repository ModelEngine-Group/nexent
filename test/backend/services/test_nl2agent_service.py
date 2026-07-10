"""Unit tests for NL2AGENT service orchestration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.nl2agent_session_catalog import (
    clear_nl2agent_session_catalogs,
    get_nl2agent_session_catalogs,
)
from services import nl2agent_service


class _FixedUuid:
    hex = "abcdef1234567890"


_RAW_TOOL_ROWS = [
    {
        "tool_id": 1,
        "name": "local_search",
        "description": "Search local documents",
        "labels": ["search"],
        "source": "local",
        "category": "retrieval",
        "usage": "local_search",
        "params": [{"name": "query", "type": "string"}],
    },
    {
        "tool_id": 2,
        "name": "remote_only",
        "description": "Remote tool should not be injected",
        "source": "remote",
    },
]
_EXPECTED_TOOL_CATALOG = [
    {
        "tool_id": 1,
        "name": "local_search",
        "description": "Search local documents",
        "labels": ["search"],
        "source": "local",
        "category": "retrieval",
        "usage": "local_search",
        "params": [{"name": "query", "type": "string"}],
    }
]
_RAW_SKILL_ROWS = [
    {
        "skill_id": 7,
        "name": "brief-writer",
        "description": "Write short research briefs",
        "tags": ["writing"],
        "config_schema": {"tone": {"type": "string"}},
    }
]
_EXPECTED_SKILL_CATALOG = [
    {
        "skill_id": 7,
        "name": "brief-writer",
        "description": "Write short research briefs",
        "tags": ["writing"],
        "config_schema": {"tone": {"type": "string"}},
    }
]
_REGISTRY_RESULTS = [{"name": "github-mcp", "description": "Repository automation"}]
_COMMUNITY_RESULTS = [{"communityId": 55, "name": "browser-mcp"}]
_OFFICIAL_SKILLS = [{"skill_id": 12, "skill_name": "code-review"}]
_EXPECTED_SESSION_CATALOGS = {
    "tool_catalog": _EXPECTED_TOOL_CATALOG,
    "skill_catalog": _EXPECTED_SKILL_CATALOG,
    "registry_results": _REGISTRY_RESULTS,
    "community_results": _COMMUNITY_RESULTS,
    "official_skills": _OFFICIAL_SKILLS,
}


@pytest.fixture(autouse=True)
def mock_nl2agent_seed_defaults(monkeypatch):
    clear_nl2agent_session_catalogs()
    monkeypatch.setattr(
        nl2agent_service,
        "get_nl2agent_seed_config",
        MagicMock(
            return_value={
                "agent_info": {
                    "name": "nl2agent",
                    "display_name": "Agent Builder",
                    "description": "NL2AGENT public description",
                    "business_description": "NL2AGENT business description",
                },
                "prompt_segments": {
                    "duty_prompt": "NL2AGENT concise duty",
                    "constraint_prompt": "NL2AGENT concise constraint",
                    "few_shots_prompt": "",
                },
                "system_prompt": "NL2AGENT full runtime system prompt",
            }
        ),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_model_records",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "list_all_tools",
        MagicMock(return_value=_RAW_TOOL_ROWS),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "list_tenant_skills",
        MagicMock(return_value=_RAW_SKILL_ROWS),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "list_registry_mcp_services",
        AsyncMock(return_value={"servers": _REGISTRY_RESULTS}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "list_community_mcp_services",
        MagicMock(return_value={"items": _COMMUNITY_RESULTS}),
    )
    monkeypatch.setattr(
        nl2agent_service,
        "get_official_skills_with_status",
        MagicMock(return_value=_OFFICIAL_SKILLS),
    )
    yield
    clear_nl2agent_session_catalogs()


def _seeded_nl2agent_info(agent_id: int = 101):
    return {
        "agent_id": agent_id,
        "name": "nl2agent",
        "display_name": "Agent Builder",
        "description": "NL2AGENT public description",
        "business_description": "NL2AGENT business description",
        "prompt_template_id": None,
        "prompt_template_name": None,
        "duty_prompt": "NL2AGENT concise duty",
        "constraint_prompt": "NL2AGENT concise constraint",
        "few_shots_prompt": "",
        "verification_config": nl2agent_service._NL2AGENT_VERIFICATION_CONFIG,
        "model_ids": [],
    }


@pytest.mark.asyncio
async def test_start_session_returns_builder_draft_and_conversation_ids(monkeypatch):
    search_builder = MagicMock(return_value=101)
    search_agent = MagicMock(return_value=_seeded_nl2agent_info())
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
        **_EXPECTED_SESSION_CATALOGS,
    }
    assert get_nl2agent_session_catalogs("tenant_1", 202) == _EXPECTED_SESSION_CATALOGS
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
    search_agent = MagicMock(return_value=_seeded_nl2agent_info())
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
    assert request.display_name == "Agent Builder"
    assert request.description == "NL2AGENT public description"
    assert request.business_description == "NL2AGENT business description"
    assert request.prompt_template_id is None
    assert request.prompt_template_name is None
    assert request.duty_prompt == "NL2AGENT concise duty"
    assert request.duty_prompt != "NL2AGENT full runtime system prompt"
    assert request.constraint_prompt == "NL2AGENT concise constraint"
    assert request.few_shots_prompt == ""
    update_agent.assert_called_once_with(
        agent_id=101,
        agent_info=request,
        user_id="user_1",
        version_no=0,
    )


@pytest.mark.asyncio
async def test_install_web_skill_installs_by_skill_name(monkeypatch):
    install_from_zip = MagicMock(return_value=["search-web-tavily"])
    monkeypatch.setattr(
        nl2agent_service, "install_skills_from_zip_for_tenant", install_from_zip
    )

    result = await nl2agent_service.install_web_skill(
        skill_id=0,
        skill_name="search-web-tavily",
        tenant_id="tenant_1",
        user_id="user_1",
        locale="en",
    )

    install_from_zip.assert_called_once_with(
        skill_names=["search-web-tavily"],
        tenant_id="tenant_1",
        user_id="user_1",
        locale="en",
    )
    assert result == {
        "skill_id": 0,
        "skill_name": "search-web-tavily",
        "installed": True,
        "installed_ids": [],
        "installed_names": ["search-web-tavily"],
    }


@pytest.mark.asyncio
async def test_install_web_skill_still_installs_by_legacy_skill_id(monkeypatch):
    install_by_id = MagicMock(return_value=[107])
    monkeypatch.setattr(nl2agent_service, "install_skills_for_tenant", install_by_id)

    result = await nl2agent_service.install_web_skill(
        skill_id=77,
        tenant_id="tenant_1",
        user_id="user_1",
    )

    install_by_id.assert_called_once_with(
        skill_ids=[77], tenant_id="tenant_1", user_id="user_1"
    )
    assert result == {
        "skill_id": 77,
        "installed": True,
        "installed_ids": [107],
    }


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


@pytest.mark.asyncio
async def test_apply_local_resources_batch_ignores_catalog_param_schema(monkeypatch):
    query_tools = MagicMock(
        return_value=[
            {
                "tool_id": 42,
                "params": [
                    {
                        "type": "integer",
                        "name": "top_k",
                        "default": None,
                        "optional": True,
                    }
                ],
            }
        ]
    )
    bind_tool = MagicMock()

    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids", query_tools)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )

    result = await nl2agent_service.apply_local_resources_batch(
        agent_id=202,
        tool_ids=[42],
        skill_ids=[],
        tenant_id="tenant_1",
        user_id="user_1",
    )

    assert result["bound_tool_count"] == 1
    tool_request = bind_tool.call_args.kwargs["tool_info"]
    assert tool_request.params == {}


@pytest.mark.asyncio
async def test_apply_local_resources_batch_rejects_invalid_draft_agent_id(monkeypatch):
    query_tools = MagicMock()
    monkeypatch.setattr(nl2agent_service, "query_tools_by_ids", query_tools)

    with pytest.raises(nl2agent_service.AgentRunException):
        await nl2agent_service.apply_local_resources_batch(
            agent_id=0,
            tool_ids=[42],
            skill_ids=[],
            tenant_id="tenant_1",
            user_id="user_1",
        )

    query_tools.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_agent_rejects_invalid_draft_agent_id(monkeypatch):
    update_agent = MagicMock()
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)

    with pytest.raises(nl2agent_service.AgentRunException):
        await nl2agent_service.finalize_agent(
            agent_id=0,
            user_id="user_1",
            tenant_id="tenant_1",
            business_description="Build a helper agent",
            tool_ids=[],
            skill_ids=[],
            sub_agent_ids=[],
        )

    update_agent.assert_not_called()


def test_seed_nl2agent_default_agent_sets_prompt_and_available_models(monkeypatch):
    seed_tools = MagicMock(return_value=[11, 12])
    query_agents = MagicMock(return_value=[])
    create_agent = MagicMock(return_value={"agent_id": 101})
    bind_tool = MagicMock()
    get_models = MagicMock(
        return_value=[
            {"model_id": 7, "model_type": "llm", "connect_status": "available"},
            {"model_id": 8, "model_type": "chat", "connect_status": "available"},
            {"model_id": 9, "model_type": "embedding", "connect_status": "available"},
            {"model_id": 10, "model_type": "llm", "connect_status": "unavailable"},
        ]
    )

    monkeypatch.setattr(nl2agent_service, "seed_nl2agent_builtin_tools", seed_tools)
    monkeypatch.setattr(
        nl2agent_service, "query_all_agent_info_by_tenant_id", query_agents
    )
    monkeypatch.setattr(nl2agent_service, "create_agent", create_agent)
    monkeypatch.setattr(nl2agent_service, "get_model_records", get_models)
    monkeypatch.setattr(
        nl2agent_service, "create_or_update_tool_by_tool_info", bind_tool
    )

    result = nl2agent_service.seed_nl2agent_default_agent(
        tenant_id="tenant_1", user_id="user_1"
    )

    assert result == 101
    payload = create_agent.call_args.args[0]
    assert payload["name"] == "nl2agent"
    assert payload["display_name"] == "Agent Builder"
    assert payload["description"] == "NL2AGENT public description"
    assert payload["business_description"] == "NL2AGENT business description"
    assert payload["prompt_template_id"] is None
    assert payload["prompt_template_name"] is None
    assert payload["duty_prompt"] == "NL2AGENT concise duty"
    assert payload["duty_prompt"] != "NL2AGENT full runtime system prompt"
    assert payload["constraint_prompt"] == "NL2AGENT concise constraint"
    assert payload["few_shots_prompt"] == ""
    assert payload["verification_config"]["enabled"] is True
    assert payload["verification_config"]["final_verification_enabled"] is True
    assert payload["verification_config"]["llm_verification_enabled"] is False
    assert payload["model_ids"] == [7, 8]
    assert payload["business_logic_model_id"] == 7


def test_seed_nl2agent_default_agent_backfills_existing_seed_defaults(
    monkeypatch,
):
    seed_tools = MagicMock(return_value=[11, 12])
    query_agents = MagicMock(
        return_value=[
            {
                "agent_id": 101,
                "name": "nl2agent",
                "display_name": "Old Builder",
                "description": "Old description",
                "business_description": "Old business description",
                "prompt_template_id": None,
                "prompt_template_name": None,
                "duty_prompt": "placeholder prompt",
                "constraint_prompt": "placeholder constraint",
                "few_shots_prompt": "placeholder few shots",
                "verification_config": None,
                "model_ids": [],
                "business_logic_model_id": None,
            }
        ]
    )
    update_agent = MagicMock()
    create_agent = MagicMock()
    get_models = MagicMock(
        return_value=[
            {"model_id": 7, "model_type": "llm", "connect_status": "available"},
            {"model_id": 8, "model_type": "chat", "connect_status": "available"},
        ]
    )

    monkeypatch.setattr(nl2agent_service, "seed_nl2agent_builtin_tools", seed_tools)
    monkeypatch.setattr(
        nl2agent_service, "query_all_agent_info_by_tenant_id", query_agents
    )
    monkeypatch.setattr(nl2agent_service, "update_agent", update_agent)
    monkeypatch.setattr(nl2agent_service, "create_agent", create_agent)
    monkeypatch.setattr(nl2agent_service, "get_model_records", get_models)

    result = nl2agent_service.seed_nl2agent_default_agent(
        tenant_id="tenant_1", user_id="user_1"
    )

    assert result == 101
    create_agent.assert_not_called()
    request = update_agent.call_args.kwargs["agent_info"]
    assert request.display_name == "Agent Builder"
    assert request.description == "NL2AGENT public description"
    assert request.business_description == "NL2AGENT business description"
    assert request.prompt_template_id is None
    assert request.prompt_template_name is None
    assert request.duty_prompt == "NL2AGENT concise duty"
    assert request.duty_prompt != "NL2AGENT full runtime system prompt"
    assert request.constraint_prompt == "NL2AGENT concise constraint"
    assert request.few_shots_prompt == ""
    assert request.verification_config["enabled"] is True
    assert request.verification_config["final_verification_enabled"] is True
    assert request.verification_config["llm_verification_enabled"] is False
    assert request.model_ids == [7, 8]
    assert request.business_logic_model_id == 7
    update_agent.assert_called_once_with(
        agent_id=101,
        agent_info=request,
        user_id="user_1",
        version_no=0,
    )
