"""Unit tests for NL2AGENT service orchestration."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import nl2agent_service


class _FixedUuid:
    hex = "abcdef1234567890"


@pytest.fixture(autouse=True)
def mock_nl2agent_seed_defaults(monkeypatch):
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


def _seeded_nl2agent_info(agent_id: int = 101):
    return {
        "agent_id": agent_id,
        "name": "nl2agent",
        "display_name": "Agent Builder",
        "description": "NL2AGENT public description",
        "business_description": "NL2AGENT business description",
        "prompt_template_id": 0,
        "prompt_template_name": "system_default",
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
    assert request.prompt_template_id == 0
    assert request.prompt_template_name == "system_default"
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
async def test_recommend_local_resources_returns_unranked_candidates_when_scoring_fails(monkeypatch):
    list_tools = AsyncMock(
        return_value=[
            {
                "tool_id": 1,
                "name": "document_reader",
                "description": "Read Word documents",
                "source": "local",
            }
        ]
    )
    list_skills = MagicMock(
        return_value=[
            {
                "skill_id": 10,
                "name": "ppt_builder",
                "description": "Create PPT reports",
                "tags": ["presentation"],
            }
        ]
    )
    score_llm = MagicMock(side_effect=RuntimeError("model unavailable"))

    monkeypatch.setattr(nl2agent_service, "list_all_tools", list_tools)
    monkeypatch.setattr(nl2agent_service, "list_tenant_skills", list_skills)
    monkeypatch.setattr(nl2agent_service, "call_llm_for_system_prompt", score_llm)

    result = await nl2agent_service.recommend_local_resources(
        query="read Word and create PPT",
        agent_id=202,
        tenant_id="tenant_1",
        model_id=9,
    )

    assert result["tools"] == [
        {
            "tool_id": 1,
            "name": "document_reader",
            "description": "Read Word documents",
            "labels": [],
            "source": "local",
            "category": "",
            "score": 0,
            "reason": "LLM scoring unavailable; shown as an unranked tool candidate.",
        }
    ]
    assert result["skills"] == [
        {
            "skill_id": 10,
            "name": "ppt_builder",
            "description": "Create PPT reports",
            "tags": ["presentation"],
            "score": 0,
            "reason": "LLM scoring unavailable; shown as an unranked skill candidate.",
        }
    ]
    assert score_llm.call_count == 2


@pytest.mark.asyncio
async def test_search_web_mcps_returns_unranked_candidates_when_scoring_fails(monkeypatch):
    registry_search = AsyncMock(
        return_value={
            "servers": [
                {
                    "server": {
                        "name": "chart-mcp",
                        "description": "Generate charts",
                        "version": "1.0.0",
                    },
                    "_meta": {
                        "io.modelcontextprotocol.registry/official": {
                            "status": "active",
                        }
                    },
                }
            ]
        }
    )
    community_search = AsyncMock(return_value={"items": []})

    monkeypatch.setattr(
        nl2agent_service, "list_registry_mcp_services", registry_search
    )
    monkeypatch.setattr(
        nl2agent_service, "list_community_mcp_services", community_search
    )
    monkeypatch.setattr(
        nl2agent_service,
        "call_llm_for_system_prompt",
        MagicMock(side_effect=RuntimeError("model unavailable")),
    )

    result = await nl2agent_service.search_web_mcps(
        query="make charts",
        tenant_id="tenant_1",
        model_id=9,
    )

    assert result == [
        {
            "name": "chart-mcp",
            "description": "Generate charts",
            "source": "registry",
            "url": "",
            "transport": "registry",
            "tools_summary": "",
            "score": 0,
            "reason": "LLM scoring unavailable; shown as an unranked MCP candidate.",
        }
    ]


@pytest.mark.asyncio
async def test_search_web_mcps_returns_unranked_candidates_when_scoring_ids_do_not_match(monkeypatch):
    registry_search = AsyncMock(return_value={"servers": []})
    community_search = AsyncMock(
        return_value={
            "items": [
                {
                    "communityId": 55,
                    "name": "browser-mcp",
                    "description": "Automate browser workflows",
                    "transportType": "url",
                    "serverUrl": "https://example.com/mcp",
                }
            ]
        }
    )

    monkeypatch.setattr(
        nl2agent_service, "list_registry_mcp_services", registry_search
    )
    monkeypatch.setattr(
        nl2agent_service, "list_community_mcp_services", community_search
    )
    monkeypatch.setattr(
        nl2agent_service,
        "call_llm_for_system_prompt",
        MagicMock(return_value='[{"mcp_id": "missing", "score": 9, "reason": "good"}]'),
    )

    result = await nl2agent_service.search_web_mcps(
        query="control a browser",
        tenant_id="tenant_1",
        model_id=9,
    )

    assert result == [
        {
            "name": "browser-mcp",
            "description": "Automate browser workflows",
            "source": "community",
            "url": "https://example.com/mcp",
            "transport": "url",
            "tools_summary": "",
            "community_id": 55,
            "score": 0,
            "reason": "LLM scoring unavailable; shown as an unranked MCP candidate.",
        }
    ]
    assert "_scoring_id" not in result[0]


@pytest.mark.asyncio
async def test_search_web_mcps_parses_nested_registry_server_payload(monkeypatch):
    # The official MCP Registry returns each entry with its fields nested under
    # a "server" object. Parsing must reach into it, otherwise name/description
    # come back empty and every candidate scores 0 (the reported bug).
    registry_search = AsyncMock(
        return_value={
            "servers": [
                {
                    "server": {
                        "name": "io.github.acme/pptx",
                        "description": "Create PowerPoint decks",
                        "version": "1.2.0",
                    },
                    "_meta": {
                        "io.modelcontextprotocol.registry/official": {
                            "serverId": "sid-1",
                            "status": "active",
                        }
                    },
                },
                {
                    "server": {
                        "name": "io.github.acme/charts",
                        "description": "Render charts",
                    },
                },
            ]
        }
    )
    community_search = AsyncMock(return_value={"items": []})

    monkeypatch.setattr(
        nl2agent_service, "list_registry_mcp_services", registry_search
    )
    monkeypatch.setattr(
        nl2agent_service, "list_community_mcp_services", community_search
    )
    monkeypatch.setattr(
        nl2agent_service,
        "call_llm_for_system_prompt",
        MagicMock(
            return_value=json.dumps(
                [
                    {
                        "mcp_id": "registry:io.github.acme/pptx",
                        "score": 9,
                        "reason": "direct match",
                    },
                    {
                        "mcp_id": "registry:io.github.acme/charts",
                        "score": 3,
                        "reason": "loosely related",
                    },
                ]
            )
        ),
    )

    result = await nl2agent_service.search_web_mcps(
        query="python-pptx",
        tenant_id="tenant_1",
        model_id=9,
    )

    # Nested registry fields are populated, not empty, and ranked by score.
    assert result == [
        {
            "name": "io.github.acme/pptx",
            "description": "Create PowerPoint decks",
            "source": "registry",
            "url": "",
            "transport": "registry",
            "tools_summary": "",
            "score": 9,
            "reason": "direct match",
        },
        {
            "name": "io.github.acme/charts",
            "description": "Render charts",
            "source": "registry",
            "url": "",
            "transport": "registry",
            "tools_summary": "",
            "score": 3,
            "reason": "loosely related",
        },
    ]
    assert all("_scoring_id" not in item for item in result)


@pytest.mark.asyncio
async def test_search_web_skills_returns_unranked_candidates_when_scoring_is_invalid(monkeypatch):
    official_skills = MagicMock(
        return_value=[
            {
                "skill_id": 77,
                "name": "doc-review",
                "description": "Review documents",
                "tags": ["documents"],
                "status": "installable",
            }
        ]
    )

    monkeypatch.setattr(
        nl2agent_service, "get_official_skills_with_status", official_skills
    )
    monkeypatch.setattr(
        nl2agent_service,
        "call_llm_for_system_prompt",
        MagicMock(return_value="not json"),
    )

    result = await nl2agent_service.search_web_skills(
        query="review documents",
        tenant_id="tenant_1",
        model_id=9,
    )

    assert result == [
        {
            "skill_id": 77,
            "skill_name": "doc-review",
            "name": "doc-review",
            "description": "Review documents",
            "tags": ["documents"],
            "status": "installable",
            "score": 0,
            "reason": "LLM scoring unavailable; shown as an unranked skill candidate.",
        }
    ]


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
    generate_prompt = MagicMock()
    monkeypatch.setattr(
        nl2agent_service,
        "generate_and_save_system_prompt_impl",
        generate_prompt,
    )

    with pytest.raises(nl2agent_service.AgentRunException):
        await nl2agent_service.finalize_agent(
            agent_id=0,
            model_id=7,
            task_description="Build a helper agent",
            tool_ids=[],
            skill_ids=[],
            sub_agent_ids=[],
            knowledge_base_display_names=[],
            user_id="user_1",
            tenant_id="tenant_1",
            language="en",
        )

    generate_prompt.assert_not_called()


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
    assert payload["prompt_template_id"] == 0
    assert payload["prompt_template_name"] == "system_default"
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
    assert request.prompt_template_id == 0
    assert request.prompt_template_name == "system_default"
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
