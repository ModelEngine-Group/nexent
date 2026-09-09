import asyncio
import json
import sys
import types
from threading import Event
from unittest.mock import AsyncMock, MagicMock

import pytest
from nexent.core.agents.context import ContextItemInput, ContextItemType
from nexent.core.utils.observer import ProcessType
from pydantic import ValidationError

from consts.model import HistoryItem, NL2AgentRunRequest
from services.nl2agent_service import (
    Nl2AgentCompletionError,
    Nl2AgentDraftSaveError,
    Nl2AgentResourceError,
    _Nl2AgentBoundaryObserver,
    _build_verified_bound_resources_context,
    _load_internal_uninstalled_resource_catalog,
    _load_installed_resource_catalog,
    _normalize_skill_config,
    _normalize_tool_config,
    _redact_installation_snapshot,
    _resource_similarity,
    build_nl2agent_run_info,
    create_nl2agent_stream,
    recommend_installed_resources_impl,
    recommend_resources_impl,
    recommend_uninstalled_resources_impl,
    save_agent_draft_fields_impl,
    search_installed_resources_impl,
    search_uninstalled_resources_impl,
    search_installed_mcp_tools_by_query,
    validate_agent_generation_complete_impl,
)
from tool_collection.mcp.nl2agent_mcp_tools import (
    AgentDraftFields,
    NL2AGENT_AGENT_ID_HEADER,
    NL2A_MCP_LEGACY_TOOL_NAMES,
    NL2A_MCP_TOOL_NAMES,
    ResourceCandidate,
    ResourceRequirement,
)
from utils.http_client_utils import create_httpx_client


@pytest.fixture
def skill_repository(monkeypatch):
    """Provide the listing boundary without initializing repository mutations."""
    import services

    module = types.ModuleType("services.skill_repository_service")
    module.list_skill_repository_listings_impl = MagicMock()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(services, "skill_repository_service", module, raising=False)
    return module


def _basic_draft_fields(**overrides):
    values = {
        "description": "Collect and summarize reliable information.",
    }
    values.update(overrides)
    return AgentDraftFields(**values)


def test_boundary_observer_stops_after_queuing_valid_nl2a_payload():
    stop_event = Event()
    observer = _Nl2AgentBoundaryObserver(lang="en", stop_event=stop_event)

    observer.add_message(
        "nl2agent",
        ProcessType.EXECUTION_LOGS,
        '<nl2a>{"subtype":"requirement_clarification","questions":['
        '{"question_id":"expected_output","question_type":"text",'
        '"title":"What should the agent produce?","required":true,'
        '"options":[],"allow_other":false,"other_input_expanded":false}'
        "]}</nl2a>"
        "\nNL2A payload generated.",
    )

    messages = [json.loads(item) for item in observer.get_cached_message()]
    assert stop_event.is_set()
    assert observer.boundary_reached is True
    assert [item["type"] for item in messages] == [
        ProcessType.NL2A.value,
        ProcessType.EXECUTION_LOGS.value,
    ]
    assert messages[1]["content"] == "NL2A payload generated."

    observer.add_message("nl2agent", ProcessType.FINAL_ANSWER, "<user_break>")
    observer.add_message(
        "nl2agent",
        ProcessType.ERROR,
        "Agent execution interrupted by external stop signal",
    )
    observer.add_message("nl2agent", ProcessType.ERROR, "real runtime failure")
    terminal_messages = [
        json.loads(item) for item in observer.get_cached_message()
    ]
    assert terminal_messages == [
        {"type": ProcessType.ERROR.value, "content": "real runtime failure"}
    ]


def test_boundary_observer_does_not_stop_for_invalid_wrapper():
    stop_event = Event()
    observer = _Nl2AgentBoundaryObserver(lang="en", stop_event=stop_event)

    observer.add_message(
        "nl2agent",
        ProcessType.EXECUTION_LOGS,
        "<nl2a>{invalid json}</nl2a>\nWrapper failed.",
    )

    assert stop_event.is_set() is False
    assert observer.boundary_reached is False


def test_update_agent_draft_changes_only_explicit_fields_and_allows_empty_list(
    mocker,
):
    mocker.patch(
        "services.agent_draft_permission_service.query_agent_records_for_nl2agent",
        return_value=[
            {
                "agent_id": 22,
                "tenant_id": "tenant-a",
                "version_no": 0,
                "delete_flag": "N",
                "created_by": "user-a",
            }
        ],
    )
    mocker.patch(
        "services.agent_draft_permission_service.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    update_fields = mocker.patch(
        "services.nl2agent_service.update_agent_draft_fields",
        return_value=1,
    )

    result = save_agent_draft_fields_impl(
        agent_id=22,
        fields=AgentDraftFields(
            duty_prompt="Updated duty",
            example_questions=[],
        ),
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert result["created"] is False
    assert result["updated_fields"] == ["duty_prompt", "example_questions"]
    update_fields.assert_called_once_with(
        agent_id=22,
        tenant_id="tenant-a",
        fields={"duty_prompt": "Updated duty", "example_questions": []},
    )


@pytest.mark.parametrize(
    ("records", "role", "expected_code"),
    [
        ([], "MEMBER", "agent_not_found"),
        (
            [
                {
                    "agent_id": 22,
                    "tenant_id": "tenant-a",
                    "version_no": 1,
                    "delete_flag": "N",
                }
            ],
            "MEMBER",
            "agent_not_draft",
        ),
        (
            [
                {
                    "agent_id": 22,
                    "tenant_id": "tenant-a",
                    "version_no": 0,
                    "delete_flag": "Y",
                }
            ],
            "MEMBER",
            "agent_deleted",
        ),
        (
            [
                {
                    "agent_id": 22,
                    "tenant_id": "tenant-a",
                    "version_no": 0,
                    "delete_flag": "N",
                    "created_by": "another-user",
                    "ingroup_permission": "READ_ONLY",
                }
            ],
            "MEMBER",
            "agent_read_only",
        ),
    ],
)
def test_update_agent_draft_rejects_invalid_identity_or_permission(
    mocker,
    records,
    role,
    expected_code,
):
    mocker.patch(
        "services.agent_draft_permission_service.query_agent_records_for_nl2agent",
        return_value=records,
    )
    mocker.patch(
        "services.agent_draft_permission_service.get_user_role_by_tenant",
        return_value=role,
    )
    update_fields = mocker.patch(
        "services.nl2agent_service.update_agent_draft_fields"
    )

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            22,
            AgentDraftFields(description="Updated"),
            "tenant-a",
            "user-a",
        )

    assert exc_info.value.code == expected_code
    update_fields.assert_not_called()


def test_agent_draft_database_failures_are_stable_and_retryable(mocker):
    mocker.patch(
        "services.agent_draft_permission_service.query_agent_records_for_nl2agent",
        return_value=[
            {
                "agent_id": 22,
                "tenant_id": "tenant-a",
                "version_no": 0,
                "delete_flag": "N",
                "created_by": "user-a",
            }
        ],
    )
    mocker.patch(
        "services.agent_draft_permission_service.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    mocker.patch(
        "services.nl2agent_service.update_agent_draft_fields",
        side_effect=RuntimeError("private database details"),
    )

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            22,
            AgentDraftFields(description="Updated"),
            "tenant-a",
            "user-a",
        )

    assert exc_info.value.code == "draft_save_failed"
    assert exc_info.value.retryable is True


def test_agent_draft_update_rejects_unexpected_row_count(mocker):
    mocker.patch(
        "services.agent_draft_permission_service.query_agent_records_for_nl2agent",
        return_value=[
            {
                "agent_id": 22,
                "tenant_id": "tenant-a",
                "version_no": 0,
                "delete_flag": "N",
                "created_by": "user-a",
            }
        ],
    )
    mocker.patch(
        "services.agent_draft_permission_service.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    mocker.patch(
        "services.nl2agent_service.update_agent_draft_fields",
        return_value=0,
    )

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            22,
            AgentDraftFields(description="Updated"),
            "tenant-a",
            "user-a",
        )

    assert exc_info.value.code == "draft_save_failed"
    assert exc_info.value.retryable is True


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"description": None},
        {"unexpected": "field"},
    ],
)
def test_agent_draft_fields_reject_empty_null_and_extra_patches(fields):
    with pytest.raises(ValidationError):
        AgentDraftFields.model_validate(fields)


def test_search_filters_catalog_and_returns_safe_metadata(mocker):
    query_tools = mocker.patch(
        "services.nl2agent_service.query_all_tools",
        return_value=[
            {
                "tool_id": 8,
                "name": "weather_search",
                "origin_name": "weather",
                "description": "Search weather forecasts",
                "source": "mcp",
                "usage": "weather-server",
                "labels": ["Weather", "Forecast"],
                "inputs": '{"city":"string"}',
                "is_available": True,
                "params": {"token": "secret"},
            },
            {
                "tool_id": 9,
                "name": "disabled_weather",
                "description": "Search weather forecasts",
                "source": "mcp",
                "usage": "weather-server",
                "is_available": False,
            },
            {
                "tool_id": 10,
                "name": "local_weather",
                "description": "Search weather forecasts",
                "source": "local",
                "is_available": True,
            },
        ],
    )

    result = search_installed_mcp_tools_by_query(
        "tenant-a",
        "weather forecast search",
    )

    query_tools.assert_called_once_with(tenant_id="tenant-a")
    assert len(result) == 1
    assert result[0].tool_id == 8
    assert result[0].source == "mcp"
    assert result[0].labels == ["Weather", "Forecast"]
    assert result[0].inputs == {"city": "string"}
    assert "params" not in result[0].model_dump()


def test_search_sorts_ties_by_tool_id_and_limits_to_five(mocker):
    mocker.patch(
        "services.nl2agent_service.query_all_tools",
        return_value=[
            {
                "tool_id": tool_id,
                "name": f"tool_{tool_id}",
                "description": "matching tool",
                "source": "mcp",
                "usage": "server",
                "is_available": True,
            }
            for tool_id in [9, 2, 7, 1, 5, 3]
        ],
    )
    mocker.patch("services.nl2agent_service.fuzz.WRatio", return_value=80)
    mocker.patch(
        "services.nl2agent_service.fuzz.token_set_ratio",
        return_value=80,
    )

    result = search_installed_mcp_tools_by_query(
        "tenant-a",
        "weather forecast search",
    )

    assert [item.tool_id for item in result] == [1, 2, 3, 5, 7]
    assert all(item.score == 0.8 for item in result)


def test_search_filters_scores_below_threshold(mocker):
    mocker.patch(
        "services.nl2agent_service.query_all_tools",
        return_value=[
            {
                "tool_id": 1,
                "name": "unrelated",
                "description": "unrelated",
                "source": "mcp",
                "usage": "server",
                "is_available": True,
            }
        ],
    )
    mocker.patch("services.nl2agent_service.fuzz.WRatio", return_value=44.9)
    mocker.patch(
        "services.nl2agent_service.fuzz.token_set_ratio",
        return_value=20,
    )

    assert search_installed_mcp_tools_by_query(
        "tenant-a",
        "weather forecast search",
    ) == []


def test_search_skips_unsearchable_tools_and_sanitizes_malformed_inputs(mocker):
    mocker.patch(
        "services.nl2agent_service.query_all_tools",
        return_value=[
            {
                "tool_id": 1,
                "name": "",
                "description": "",
                "source": "mcp",
                "is_available": True,
            },
            {
                "tool_id": 2,
                "name": "weather_lookup",
                "description": "  Current\n weather  ",
                "source": "mcp",
                "usage": "weather-server",
                "labels": "weather",
                "inputs": "not a schema",
                "is_available": True,
            },
            {
                "tool_id": 3,
                "name": "weather_alerts",
                "description": "Weather alerts",
                "source": "mcp",
                "usage": "weather-server",
                "labels": ["weather", None],
                "inputs": '["not", "an", "object"]',
                "is_available": True,
            },
            {
                "tool_id": 4,
                "name": "weather_options",
                "description": "Weather query options",
                "source": "mcp",
                "usage": "weather-server",
                "labels": [],
                "inputs": {"conditions": (" rainy ", " sunny ")},
                "is_available": True,
            },
        ],
    )
    mocker.patch("services.nl2agent_service.fuzz.WRatio", return_value=90)
    mocker.patch("services.nl2agent_service.fuzz.token_set_ratio", return_value=90)

    result = search_installed_mcp_tools_by_query(
        "tenant-a",
        "weather",
        limit=3,
    )

    assert [item.tool_id for item in result] == [2, 3, 4]
    assert result[0].description == "Current weather"
    assert result[0].labels == []
    assert result[0].inputs == {}
    assert result[1].labels == ["weather"]
    assert result[1].inputs == {}
    assert result[2].inputs == {"conditions": ["rainy", "sunny"]}
    assert search_installed_mcp_tools_by_query(
        "tenant-a",
        None,
        limit=-1,
    ) == []


@pytest.mark.asyncio
async def test_search_installed_resources_covers_visible_tools_and_skills(mocker):
    mocker.patch(
        "services.tool_configuration_service.list_all_tools",
        new=AsyncMock(
            return_value=[
                {
                    "tool_id": 7,
                    "name": "weather_forecast",
                    "description": "Weather forecast lookup",
                    "description_zh": "天气预报查询",
                    "source": "local",
                    "is_available": True,
                    "params": [],
                    "inputs": '{"city":{"type":"string"}}',
                    "labels": ["weather"],
                },
                {
                    "tool_id": 8,
                    "name": "disabled_weather",
                    "description": "Weather forecast lookup",
                    "source": "mcp",
                    "is_available": False,
                },
                {
                    "tool_id": 9,
                    "name": "langchain_weather",
                    "description": "Weather forecast lookup",
                    "source": "langchain",
                    "is_available": True,
                },
                {
                    "tool_id": 10,
                    "name": "wrapper",
                    "description": "Wrap arbitrary text",
                    "source": "local",
                    "is_available": True,
                },
                {
                    "tool_id": 12,
                    "name": "knowledge_base_search",
                    "description": "Search private knowledge bases",
                    "description_zh": "检索私有知识库",
                    "source": "local",
                    "is_available": True,
                    "is_user_selectable": False,
                    "params": [
                        {
                            "name": "top_k",
                            "type": "integer",
                            "optional": False,
                            "default": 5,
                        }
                    ],
                    "inputs": {},
                },
                {
                    "tool_id": 13,
                    "name": "aidp_search",
                    "description": "Search AIDP",
                    "source": "local",
                    "is_available": True,
                    "is_user_selectable": False,
                    "params": [],
                    "inputs": {},
                },
                *[
                    {
                        "tool_id": tool_id,
                        "name": name,
                        "description": "Internal NL2Agent tool",
                        "source": "local",
                        "is_available": True,
                    }
                    for tool_id, name in enumerate(
                        (*NL2A_MCP_LEGACY_TOOL_NAMES, *NL2A_MCP_TOOL_NAMES),
                        start=20,
                    )
                ],
            ]
        ),
    )
    mocker.patch(
        "management.services.skill.service.SkillService.list_visible_skills",
        return_value=[
            {
                "skill_id": 11,
                "name": "daily_report",
                "description": "Create a concise daily report",
                "source": "custom",
                "tags": ["report"],
                "config_schemas": [],
            }
        ],
    )

    catalog = await _load_installed_resource_catalog(
        tenant_id="tenant-a",
        user_id="user-a",
    )
    catalog_by_name = {item["name"]: item for item in catalog}
    assert "wrapper" in catalog_by_name
    assert "knowledge_base_search" in catalog_by_name
    assert "aidp_search" in catalog_by_name
    assert catalog_by_name["knowledge_base_search"]["config"] == [
        {
            "name": "top_k",
            "type": "number",
            "required": True,
            "value": 5,
            "description": "",
            "description_zh": "",
        }
    ]
    assert catalog_by_name["aidp_search"]["config"] == []

    result = await search_installed_resources_impl(
        requirements=[
            ResourceRequirement(
                requirement_id="weather",
                query="weather forecast",
                search_terms=["天气预报"],
            ),
            ResourceRequirement(
                requirement_id="report",
                query="daily report",
            ),
        ],
        tenant_id="tenant-a",
        user_id="user-a",
    )

    refs = {candidate.candidate_ref for candidate in result.candidates}
    assert refs == {"tool:7", "skill:11"}
    assert result.uncovered_requirement_ids == []
    assert {candidate.source for candidate in result.candidates} == {
        "LOCAL_TOOL",
        "INSTALLED_SKILL",
    }

    knowledge_result = await search_installed_resources_impl(
        requirements=[
            ResourceRequirement(
                requirement_id="knowledge",
                query="knowledge base search",
                resource_name_hint="knowledge_base_search",
            )
        ],
        tenant_id="tenant-a",
        user_id="user-a",
    )
    assert knowledge_result.candidates[0].candidate_ref == "tool:12"
    assert knowledge_result.uncovered_requirement_ids == []


def test_resource_config_normalization_is_frontend_safe():
    assert _normalize_tool_config(None) == []
    assert _normalize_tool_config(
        [
            None,
            {"name": ""},
            {
                "name": "limit",
                "type": "integer",
                "optional": False,
                "default": 10,
                "depends_on": "enabled",
            },
        ]
    ) == [
        {
            "name": "limit",
            "type": "number",
            "required": True,
            "value": 10,
            "description": "",
            "description_zh": "",
            "depends_on": "enabled",
        }
    ]
    assert _normalize_tool_config(
        [
            {
                "name": "index_names",
                "type": "string",
                "optional": True,
                "default": None,
            }
        ]
    ) == [
        {
            "name": "index_names",
            "type": "string",
            "required": False,
            "value": None,
            "description": "",
            "description_zh": "",
        }
    ]
    assert _normalize_skill_config({"config_schemas": None}) == []
    skill_config = _normalize_skill_config(
        {
            "config_schemas": [
                None,
                {"name": ""},
                {"name": "region", "type": "string", "default": "global"},
            ],
            "config_values": {"region": "eu"},
        }
    )
    assert skill_config == [
        {"name": "region", "type": "string", "required": True, "value": "eu"}
    ]
    assert _resource_similarity("", "search") == 0


@pytest.mark.asyncio
async def test_search_internal_uninstalled_resources_aggregates_sources_and_excludes_refs(
    mocker, skill_repository,
):
    mocker.patch(
        "management.services.skill.service.get_official_skills_with_status",
        return_value=[
            {
                "skill_id": 0,
                "name": "daily-report",
                "description": "Create daily reports",
                "status": "installable",
            },
            {
                "skill_id": 9,
                "name": "installed-skill",
                "description": "Already installed",
                "status": "installed",
            },
        ],
    )
    mocker.patch(
        "services.skill_repository_service.list_skill_repository_listings_impl",
        return_value={
            "items": [
                {
                    "skill_repository_id": 31,
                    "name": "email-report",
                    "description": "Send reports by email",
                    "content": "email report delivery",
                    "tags": ["email"],
                }
            ],
            "pagination": {"total_pages": 1},
        },
    )
    mocker.patch(
        "services.mcp_management_service.list_community_mcp_services",
        new=AsyncMock(
            return_value={
                "items": [
                    {
                        "marketId": 42,
                        "name": "github-search",
                        "description": "Search GitHub projects",
                        "content": "GitHub repository search",
                        "transportType": "url",
                        "serverUrl": "https://mcp.example.test/mcp",
                        "authorizationToken": "persisted-secret",
                        "customHeaders": {"X-Secret": "persisted-secret"},
                        "tags": ["github"],
                    }
                ],
                "nextCursor": None,
            }
        ),
    )

    result = await search_uninstalled_resources_impl(
        requirements=[
            ResourceRequirement(
                requirement_id="github",
                query="GitHub project search",
                search_terms=["github-search"],
            ),
            ResourceRequirement(
                requirement_id="email",
                query="email report delivery",
                search_terms=["email-report"],
            ),
        ],
        exclude_refs=["nexent_official_skill:daily-report"],
        tenant_id="tenant-a",
        user_id="user-a",
    )

    refs = {candidate.candidate_ref for candidate in result.candidates}
    assert "nexent_official_skill:daily-report" not in refs
    assert refs == {
        "tenant_skill_repository:31",
        "tenant_mcp_repository:42",
    }
    assert result.uncovered_requirement_ids == []


@pytest.mark.asyncio
async def test_recommend_uninstalled_resources_overwrites_snapshot_and_redacts_secrets(
    mocker,
):
    actual = {
        "candidate_ref": "tenant_mcp_repository:42",
        "resource_type": "mcp_server",
        "source": "TENANT_MCP_REPOSITORY",
        "name": "verified-name",
        "description": "Verified description",
        "form_kind": "MCP_REMOTE",
        "config": {"authorizationToken": ""},
        "installation_options": [
            {
                "option_id": "repository",
                "label": "Install",
                "form_kind": "MCP_REMOTE",
                "config": {"authorizationToken": ""},
            }
        ],
        "default_option_id": "repository",
    }
    mocker.patch(
        "services.nl2agent_service._load_internal_uninstalled_resource_catalog",
        new=AsyncMock(return_value=[actual]),
    )
    supplied = ResourceCandidate(
        candidate_ref="tenant_mcp_repository:42",
        resource_type="mcp_server",
        source="TENANT_MCP_REPOSITORY",
        name="tampered-name",
        description="Tampered description",
        requirement_ids=["search"],
        score=0.91,
    )

    result = await recommend_uninstalled_resources_impl(
        candidates=[supplied],
        recommended_refs=[supplied.candidate_ref],
        tenant_id="tenant-a",
        user_id="user-a",
    )

    resource = result.resources[0]
    assert resource.candidate.name == "verified-name"
    assert resource.config == {"authorizationToken": ""}
    assert resource.default_option_id == "repository"


def test_installation_snapshot_redacts_nested_secret_shapes():
    redacted = _redact_installation_snapshot({
        "customHeaders": {
            "Authorization": "Bearer private-token",
            "X-Trace": "private-trace",
        },
        "environment": {
            "API_TOKEN": "private-token",
            "REGION": "private-region",
        },
        "fields": [
            {
                "name": "password",
                "value": "private-password",
                "default": "private-default",
                "isSecret": True,
            },
            {"name": "region", "value": "eu-west"},
        ],
        "api_key": "private-key",
        "nested": {
            "accessToken": "private-access-token",
            "safe": "visible",
        },
    })

    assert redacted == {
        "customHeaders": {"Authorization": "", "X-Trace": ""},
        "environment": {"API_TOKEN": "", "REGION": ""},
        "fields": [
            {
                "name": "password",
                "value": "",
                "default": "",
                "isSecret": True,
            },
            {"name": "region", "value": "eu-west"},
        ],
        "api_key": "",
        "nested": {"accessToken": "", "safe": "visible"},
    }
    assert _redact_installation_snapshot(
        "private-value", parent_key="environment"
    ) == ""
    assert _redact_installation_snapshot("visible", parent_key="name") == "visible"


@pytest.mark.asyncio
async def test_uninstalled_catalog_paginates_and_filters_invalid_entries(mocker, skill_repository):
    mocker.patch(
        "management.services.skill.service.get_official_skills_with_status",
        return_value=[
            {
                "name": "PDF report",
                "description": "Create a PDF report",
                "status": "installable",
            },
            {"name": "", "status": "installable"},
        ],
    )
    list_skills = mocker.patch(
        "services.skill_repository_service.list_skill_repository_listings_impl",
        side_effect=[
            {
                "items": [
                    None,
                    {
                        "id": 32,
                        "name": "tenant-report",
                        "description": "Create tenant reports",
                    },
                    {"skill_repository_id": 0, "name": "invalid-id"},
                    {"skill_repository_id": 33, "name": ""},
                ],
                "pagination": {"total_pages": 2},
            },
            {"items": [], "pagination": {"total_pages": 2}},
        ],
    )
    list_community = mocker.patch(
        "services.mcp_management_service.list_community_mcp_services",
        new=AsyncMock(
            side_effect=[
                {
                    "items": [
                        None,
                        {
                            "communityId": 55,
                            "name": "container-mcp",
                            "description": "Run a container MCP service",
                            "transportType": "container",
                            "configJson": {
                                "env": {"API_TOKEN": "private-token"}
                            },
                            "registryJson": {"apiKey": "private-key"},
                        },
                        {
                            "marketId": 56,
                            "name": "invalid-container",
                            "transportType": "container",
                            "configJson": "not-an-object",
                        },
                        {
                            "marketId": 0,
                            "name": "invalid-id",
                            "transportType": "url",
                            "serverUrl": "https://mcp.example.test",
                        },
                        {
                            "marketId": 57,
                            "name": "invalid-url",
                            "transportType": "url",
                            "serverUrl": "ftp://mcp.example.test",
                        },
                    ],
                    "nextCursor": "next-page",
                },
                {"items": [], "nextCursor": None},
            ]
        ),
    )

    catalog = await _load_internal_uninstalled_resource_catalog(
        tenant_id="tenant-a",
        user_id="user-a",
    )

    by_ref = {item["candidate_ref"]: item for item in catalog}
    assert set(by_ref) == {
        "nexent_official_skill:PDF%20report",
        "tenant_skill_repository:32",
        "tenant_mcp_repository:55",
    }
    container = by_ref["tenant_mcp_repository:55"]
    assert container["form_kind"] == "MCP_CONTAINER"
    assert json.loads(container["config"]["containerConfigJson"]) == {
        "env": {"API_TOKEN": ""}
    }
    assert container["config"]["registryJson"] == {"apiKey": ""}
    assert [call.kwargs["page"] for call in list_skills.call_args_list] == [1, 2]
    assert [
        call.kwargs["cursor"] for call in list_community.await_args_list
    ] == [None, "next-page"]


@pytest.mark.asyncio
async def test_recommend_uninstalled_resources_rejects_missing_and_mismatched_entries(
    mocker,
):
    load_catalog = mocker.patch(
        "services.nl2agent_service._load_internal_uninstalled_resource_catalog",
        new=AsyncMock(return_value=[]),
    )
    supplied = ResourceCandidate(
        candidate_ref="tenant_skill_repository:31",
        resource_type="skill",
        source="TENANT_SKILL_REPOSITORY",
        name="tenant-report",
        requirement_ids=["report"],
        score=0.9,
    )

    with pytest.raises(Nl2AgentResourceError, match="resource_not_visible"):
        await recommend_uninstalled_resources_impl(
            candidates=[supplied],
            recommended_refs=[],
            tenant_id="tenant-a",
            user_id="user-a",
        )

    load_catalog.return_value = [{
        "candidate_ref": supplied.candidate_ref,
        "resource_type": "mcp_server",
        "source": "TENANT_MCP_REPOSITORY",
    }]
    with pytest.raises(Nl2AgentResourceError, match="invalid_candidates"):
        await recommend_uninstalled_resources_impl(
            candidates=[supplied],
            recommended_refs=[],
            tenant_id="tenant-a",
            user_id="user-a",
        )


@pytest.mark.asyncio
async def test_recommend_resources_dispatches_homogeneous_sources(mocker):
    installed = ResourceCandidate(
        candidate_ref="tool:7",
        resource_type="tool",
        source="LOCAL_TOOL",
        name="search",
        requirement_ids=["lookup"],
        score=0.9,
    )
    uninstalled = ResourceCandidate(
        candidate_ref="tenant_skill_repository:31",
        resource_type="skill",
        source="TENANT_SKILL_REPOSITORY",
        name="tenant-report",
        requirement_ids=["report"],
        score=0.9,
    )
    installed_result = MagicMock()
    uninstalled_result = MagicMock()
    installed_resolver = mocker.patch(
        "services.nl2agent_service.recommend_installed_resources_impl",
        new=AsyncMock(return_value=installed_result),
    )
    uninstalled_resolver = mocker.patch(
        "services.nl2agent_service.recommend_uninstalled_resources_impl",
        new=AsyncMock(return_value=uninstalled_result),
    )

    assert await recommend_resources_impl(
        agent_id=42,
        candidates=[installed],
        recommended_refs=[installed.candidate_ref],
        tenant_id="tenant-a",
        user_id="user-a",
    ) is installed_result
    assert await recommend_resources_impl(
        agent_id=42,
        candidates=[uninstalled],
        recommended_refs=[],
        tenant_id="tenant-a",
        user_id="user-a",
    ) is uninstalled_result
    installed_resolver.assert_awaited_once()
    uninstalled_resolver.assert_awaited_once()

    for candidates in ([], [installed, uninstalled]):
        with pytest.raises(Nl2AgentResourceError, match="invalid_candidates"):
            await recommend_resources_impl(
                agent_id=42,
                candidates=candidates,
                recommended_refs=[],
                tenant_id="tenant-a",
                user_id="user-a",
            )


@pytest.mark.asyncio
async def test_recommend_resources_overwrites_model_display_fields(mocker):
    mocker.patch(
        "services.nl2agent_service._load_installed_resource_catalog",
        new=AsyncMock(
            return_value=[
                {
                    "candidate_ref": "tool:7",
                    "resource_type": "tool",
                    "source": "LOCAL_TOOL",
                    "name": "verified_name",
                    "description": "Verified description",
                    "config": [
                        {
                            "name": "region",
                            "type": "string",
                            "required": True,
                            "value": "global",
                        }
                    ],
                }
            ]
        ),
    )
    query_bound_tools = mocker.patch(
        "services.nl2agent_service.query_all_enabled_tool_instances",
        return_value=[{"tool_id": 7}],
    )
    supplied = ResourceCandidate(
        candidate_ref="tool:7",
        resource_type="tool",
        source="LOCAL_TOOL",
        name="tampered_name",
        description="Tampered description",
        requirement_ids=["search"],
        score=0.91,
    )

    result = await recommend_installed_resources_impl(
        agent_id=42,
        candidates=[supplied],
        recommended_refs=["tool:7"],
        tenant_id="tenant-a",
        user_id="user-a",
    )

    resource = result.resources[0]
    assert resource.candidate.name == "verified_name"
    assert resource.candidate.description == "Verified description"
    assert resource.candidate.requirement_ids == ["search"]
    assert resource.recommendation == "recommended"
    assert resource.is_bound is True
    assert resource.form_kind == "TOOL_CONFIG"
    query_bound_tools.assert_called_once_with(
        agent_id=42,
        tenant_id="tenant-a",
        version_no=0,
    )


@pytest.mark.asyncio
async def test_recommend_resources_rejects_missing_or_mismatched_catalog_entries(mocker):
    load_catalog = mocker.patch(
        "services.nl2agent_service._load_installed_resource_catalog",
        new=AsyncMock(return_value=[]),
    )
    supplied = ResourceCandidate(
        candidate_ref="tool:7",
        resource_type="tool",
        source="LOCAL_TOOL",
        name="search",
        requirement_ids=["lookup"],
        score=0.9,
    )
    mocker.patch(
        "services.nl2agent_service.query_all_enabled_tool_instances",
        return_value=[],
    )

    with pytest.raises(Nl2AgentResourceError) as missing:
        await recommend_installed_resources_impl(
            agent_id=42,
            candidates=[supplied],
            recommended_refs=[],
            tenant_id="tenant-a",
            user_id="user-a",
        )
    assert missing.value.code == "resource_not_visible"

    load_catalog.return_value = [
        {
            "candidate_ref": "tool:7",
            "resource_type": "skill",
            "source": "INSTALLED_SKILL",
        }
    ]
    with pytest.raises(Nl2AgentResourceError) as mismatched:
        await recommend_installed_resources_impl(
            agent_id=42,
            candidates=[supplied],
            recommended_refs=[],
            tenant_id="tenant-a",
            user_id="user-a",
        )
    assert mismatched.value.code == "invalid_candidates"


@pytest.mark.asyncio
async def test_verified_binding_context_rereads_database_without_secret_values(mocker):
    mocker.patch(
        "services.nl2agent_service.require_agent_draft_edit",
        return_value={
            "name": "current_assistant",
            "description": "Current authoritative description",
            "business_description": "Legacy workflow description",
        },
    )
    mocker.patch(
        "services.nl2agent_service._load_installed_resource_catalog",
        new=AsyncMock(
            return_value=[
                {
                    "candidate_ref": "tool:7",
                    "name": "weather_forecast",
                    "description": "Weather lookup",
                    "inputs": {
                        "city": {"type": "string", "default": "catalog-secret"}
                    },
                    "config": [],
                },
                {
                    "candidate_ref": "skill:11",
                    "name": "daily_report",
                    "description": "Create a report",
                    "inputs": {},
                    "config": [
                        {"name": "api_key", "value": "catalog-skill-secret"}
                    ],
                }
            ]
        ),
    )
    mocker.patch(
        "services.nl2agent_service.query_all_enabled_tool_instances",
        return_value=[{"tool_id": 7, "params": {"api_key": "private-secret"}}],
    )
    mocker.patch(
        "services.nl2agent_service.query_enabled_skill_instances",
        return_value=[
            {
                "skill_id": 11,
                "config_values": {"api_key": "instance-skill-secret"},
            }
        ],
    )

    context = await _build_verified_bound_resources_context(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert context.id == "system:nl2agent_bound_resources"
    assert "current_assistant" in context.content["text"]
    assert "Current authoritative description" in context.content["text"]
    assert "Legacy workflow description" not in context.content["text"]
    assert "weather_forecast" in context.content["text"]
    assert "api_key" in context.content["text"]
    assert "private-secret" not in context.content["text"]
    assert "catalog-secret" not in context.content["text"]
    assert "daily_report" in context.content["text"]
    assert "catalog-skill-secret" not in context.content["text"]
    assert "instance-skill-secret" not in context.content["text"]
    assert "999" not in context.content["text"]


@pytest.mark.asyncio
async def test_validate_agent_generation_complete_uses_database_state(mocker):
    draft = {
        "name": "database_assistant",
        "display_name": "Database Assistant",
        "description": "Database-backed description",
        "duty_prompt": "Verify sources and produce a report.",
        "constraint_prompt": "1. Use weather_forecast for current weather.",
        "few_shots_prompt": "Task 1: Check the weather.",
        "greeting_message": "Hello, I can verify information.",
        "example_questions": ["What is the weather?"],
    }
    facts = [
        {
            "resource_type": "tool",
            "resource_id": 7,
            "name": "weather_forecast",
            "description": "Weather lookup",
        }
    ]
    load_state = mocker.patch(
        "services.nl2agent_service._load_verified_nl2agent_state",
        new_callable=AsyncMock,
        return_value=(draft, facts),
    )

    await validate_agent_generation_complete_impl(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )

    load_state.assert_awaited_once_with(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
async def test_validate_agent_generation_complete_allows_empty_resource_prompts(
    mocker,
):
    mocker.patch(
        "services.nl2agent_service._load_verified_nl2agent_state",
        new_callable=AsyncMock,
        return_value=(
            {
                "name": "writing_assistant",
                "display_name": "Writing Assistant",
                "description": "Improve writing",
                "duty_prompt": "Help users improve their writing.",
                "constraint_prompt": "",
                "few_shots_prompt": None,
                "greeting_message": "Hello, what should we write?",
                "example_questions": ["Improve this paragraph"],
            },
            [],
        ),
    )

    await validate_agent_generation_complete_impl(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
async def test_validate_agent_generation_complete_rejects_incomplete_resource_prompts(
    mocker,
):
    mocker.patch(
        "services.nl2agent_service._load_verified_nl2agent_state",
        new_callable=AsyncMock,
        return_value=(
            {
                "name": "research_assistant",
                "display_name": "Research Assistant",
                "description": "Research help",
                "duty_prompt": "Research sources.",
                "constraint_prompt": "Use search.",
                "few_shots_prompt": "",
                "greeting_message": "Hello",
                "example_questions": ["Research this topic"],
            },
            [
                {
                    "resource_type": "tool",
                    "resource_id": 7,
                    "name": "search",
                    "description": "Search sources",
                }
            ],
        ),
    )

    with pytest.raises(Nl2AgentCompletionError) as exc_info:
        await validate_agent_generation_complete_impl(
            agent_id=42,
            tenant_id="tenant-a",
            user_id="user-a",
        )

    assert exc_info.value.code == "prompt_fields_incomplete"
    assert exc_info.value.failed_fields == ["few_shots_prompt"]


@pytest.mark.asyncio
async def test_validate_agent_generation_complete_requires_description(mocker):
    mocker.patch(
        "services.nl2agent_service._load_verified_nl2agent_state",
        new_callable=AsyncMock,
        return_value=({"description": " "}, []),
    )

    with pytest.raises(Nl2AgentCompletionError) as exc_info:
        await validate_agent_generation_complete_impl(
            agent_id=42,
            tenant_id="tenant-a",
            user_id="user-a",
        )

    assert exc_info.value.code == "draft_fields_incomplete"
    assert exc_info.value.failed_fields == ["description"]


@pytest.mark.asyncio
async def test_build_run_info_is_ephemeral(mocker):
    default_model = {
        "model_factory": "openai",
        "model_name": "gpt-4o",
        "context_window_tokens": 32768,
    }
    capacity_snapshot = {"capacity_fingerprint": "capacity-fingerprint"}
    resolved_capacity_snapshot = MagicMock(context_window_tokens=32768)
    safe_input_budget_snapshot = {
        "soft_input_budget_tokens": 24000,
        "hard_input_budget_tokens": 30000,
    }
    join_query = mocker.patch(
        "services.nl2agent_service.join_minio_file_description_to_query",
        new_callable=AsyncMock,
        return_value="final query",
    )
    mocker.patch(
        "services.nl2agent_service.create_model_config_list",
        new_callable=AsyncMock,
        return_value=[],
    )
    get_model_config = mocker.patch(
        "services.nl2agent_service.tenant_config_manager.get_model_config",
        return_value=default_model,
    )
    resolve_input_budget = mocker.patch(
        "services.nl2agent_service._resolve_input_budget",
        return_value=(32768, capacity_snapshot, resolved_capacity_snapshot),
    )
    resolve_safe_input_budget = mocker.patch(
        "services.nl2agent_service._resolve_safe_input_budget",
        return_value=safe_input_budget_snapshot,
    )
    mocker.patch(
        "services.nl2agent_service.LOCAL_MCP_SERVER",
        "http://local-mcp:5011",
    )
    get_current_user = mocker.patch(
        "services.nl2agent_service.get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    verified_context = ContextItemInput(
        id="system:nl2agent_bound_resources",
        type=ContextItemType.SYSTEM,
        content={"text": "verified draft state"},
        source=("database:agent_bindings",),
    )
    build_verified_context = mocker.patch(
        "services.nl2agent_service._build_verified_bound_resources_context",
        new_callable=AsyncMock,
        return_value=verified_context,
    )
    request = NL2AgentRunRequest(
        query="Build an agent that summarizes weather risks.",
        agent_id=42,
        history=[
            HistoryItem(
                role="user",
                content="Build an agent that summarizes weather risks.",
            ),
            HistoryItem(
                role="assistant",
                content="I found matching weather tools.",
            ),
        ],
    )

    run_info = await build_nl2agent_run_info(
        request,
        "tenant-a",
        "en",
        "Bearer tenant-token",
    )

    assert run_info.query == "final query"
    assert run_info.agent_config.name == "__nl2agent_runtime__"
    assert run_info.agent_config.context_manager_config.token_threshold == 24000
    assert (
        run_info.agent_config.context_manager_config.hard_input_budget_tokens
        == 30000
    )
    assert run_info.agent_config.capacity_snapshot == capacity_snapshot
    assert (
        run_info.agent_config.safe_input_budget_snapshot
        == safe_input_budget_snapshot
    )
    assert run_info.capacity_snapshot == capacity_snapshot
    assert run_info.safe_input_budget_snapshot == safe_input_budget_snapshot
    assert run_info.history[0].content == (
        "Build an agent that summarizes weather risks."
    )
    assert len(run_info.context_input.items) == 3
    prompt_context = run_info.context_input.items[0]
    assert prompt_context.id == "system:nl2agent_prompt"
    assert prompt_context.type == ContextItemType.SYSTEM
    assert "### Role" in prompt_context.content["text"]
    assert run_info.context_input.items[1] == verified_context
    history_item = run_info.context_input.items[2]
    assert history_item.type.value == "conversation_turn"
    assert history_item.content == {
        "user_message": "Build an agent that summarizes weather risks.",
        "assistant_final_answer": "I found matching weather tools.",
        "attachments": [],
        "user_message_id": -1,
        "assistant_message_id": -2,
    }
    assert history_item.metadata == {"layout_order": 0}
    assert run_info.mcp_host == [
        {
            "url": "http://local-mcp:5011/sse",
            "transport": "sse",
            "httpx_client_factory": create_httpx_client,
            "bypass_proxy": True,
            "headers": {
                "Authorization": "Bearer tenant-token",
                NL2AGENT_AGENT_ID_HEADER: "42",
            },
        }
    ]
    assert run_info.sandbox_config is None
    assert run_info.redis_client is None
    assert run_info.enable_planning is False
    assert run_info.observer.enable_nl2a_wrapper is True
    assert isinstance(run_info.observer, _Nl2AgentBoundaryObserver)
    assert run_info.observer._boundary_stop_event is run_info.stop_event
    join_query.assert_awaited_once_with(
        minio_files=None,
        query="Build an agent that summarizes weather risks.",
        history=request.history,
    )
    get_model_config.assert_called_once_with(
        key="LLM_ID",
        tenant_id="tenant-a",
    )
    resolve_input_budget.assert_called_once_with(default_model)
    resolve_safe_input_budget.assert_called_once_with(
        capacity_snapshot=resolved_capacity_snapshot,
        tenant_id="tenant-a",
        agent_requested_output_tokens=None,
        request_requested_output_tokens=None,
    )
    get_current_user.assert_called_once_with("Bearer tenant-token")
    build_verified_context.assert_awaited_once_with(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
async def test_build_run_info_rejects_request_action_agent_mismatch(mocker):
    mocker.patch(
        "services.nl2agent_service.join_minio_file_description_to_query",
        new_callable=AsyncMock,
        return_value="structured action",
    )
    mocker.patch(
        "services.nl2agent_service.create_model_config_list",
        new_callable=AsyncMock,
        return_value=[],
    )
    build_verified_context = mocker.patch(
        "services.nl2agent_service._build_verified_bound_resources_context",
        new_callable=AsyncMock,
    )
    request = NL2AgentRunRequest(
        agent_id=42,
        query=json.dumps(
            {
                "type": "nl2agent_card_action",
                "subtype": "requirement_clarification",
                "agent_id": 43,
                "action": "submit",
                "result": {"answers": []},
            }
        ),
    )

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        await build_nl2agent_run_info(
            request,
            tenant_id="tenant-a",
            language="en",
            authorization="Bearer tenant-token",
        )

    assert exc_info.value.code == "agent_context_mismatch"
    build_verified_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_run_info_rejects_card_action_without_agent_id(mocker):
    build_verified_context = mocker.patch(
        "services.nl2agent_service._build_verified_bound_resources_context",
        new_callable=AsyncMock,
    )
    request = NL2AgentRunRequest(
        agent_id=42,
        query=json.dumps(
            {
                "type": "nl2agent_card_action",
                "subtype": "requirement_clarification",
                "action": "submit",
                "result": {"answers": []},
            }
        ),
    )

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        await build_nl2agent_run_info(
            request,
            tenant_id="tenant-a",
            language="en",
            authorization="Bearer tenant-token",
        )

    assert exc_info.value.code == "agent_context_mismatch"
    build_verified_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_run_info_rejects_authenticated_tenant_mismatch(mocker):
    mocker.patch(
        "services.nl2agent_service.get_current_user_id",
        return_value=("user-a", "tenant-b"),
    )
    build_verified_context = mocker.patch(
        "services.nl2agent_service._build_verified_bound_resources_context",
        new_callable=AsyncMock,
    )

    with pytest.raises(PermissionError, match="tenant mismatch"):
        await build_nl2agent_run_info(
            NL2AgentRunRequest(query="Update this Agent", agent_id=42),
            tenant_id="tenant-a",
            language="en",
            authorization="Bearer tenant-token",
        )

    build_verified_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_run_info_falls_back_without_capacity_snapshot(mocker):
    mocker.patch(
        "services.nl2agent_service.join_minio_file_description_to_query",
        new_callable=AsyncMock,
        return_value="Build a writing assistant",
    )
    model_configs = []
    mocker.patch(
        "services.nl2agent_service.create_model_config_list",
        new_callable=AsyncMock,
        return_value=model_configs,
    )
    mocker.patch(
        "services.nl2agent_service.tenant_config_manager.get_model_config",
        return_value={"model_name": "tenant-default"},
    )
    capacity_snapshot = {"capacity_fingerprint": "legacy-capacity"}
    mocker.patch(
        "services.nl2agent_service._resolve_input_budget",
        return_value=(8192, capacity_snapshot, None),
    )
    mocker.patch(
        "services.nl2agent_service._resolve_safe_input_budget",
        return_value=None,
    )
    mocker.patch(
        "services.nl2agent_service.LOCAL_MCP_SERVER",
        "http://local-mcp:5011/base/",
    )
    mocker.patch(
        "services.nl2agent_service.get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    verified_context = ContextItemInput(
        id="system:nl2agent_bound_resources",
        type=ContextItemType.SYSTEM,
        content={"text": "verified draft state"},
        source=("database:agent_bindings",),
    )
    mocker.patch(
        "services.nl2agent_service._build_verified_bound_resources_context",
        new_callable=AsyncMock,
        return_value=verified_context,
    )

    run_info = await build_nl2agent_run_info(
        NL2AgentRunRequest(query="Build a writing assistant", agent_id=42),
        tenant_id="tenant-a",
        language="en",
        authorization=None,
    )

    context_config = run_info.agent_config.context_manager_config
    assert context_config.token_threshold == 8192
    assert context_config.context_window_tokens == 8192
    assert context_config.soft_input_budget_tokens == 0
    assert context_config.hard_input_budget_tokens == 0
    assert run_info.model_config_list == model_configs
    assert run_info.history == []
    assert len(run_info.context_input.items) == 2
    prompt_context = run_info.context_input.items[0]
    assert prompt_context.id == "system:nl2agent_prompt"
    assert prompt_context.type == ContextItemType.SYSTEM
    assert "### Role" in prompt_context.content["text"]
    assert run_info.context_input.items[1] == verified_context
    assert run_info.mcp_host == [
        {
            "url": "http://local-mcp:5011/base/sse",
            "transport": "sse",
            "httpx_client_factory": create_httpx_client,
            "bypass_proxy": True,
            "headers": {NL2AGENT_AGENT_ID_HEADER: "42"},
        }
    ]


@pytest.mark.asyncio
async def test_create_stream_wraps_sdk_chunks_and_stops_run(mocker):
    run_info = MagicMock()
    run_info.stop_event = MagicMock()
    build_run_info = mocker.patch(
        "services.nl2agent_service.build_nl2agent_run_info",
        new_callable=AsyncMock,
        return_value=run_info,
    )

    async def fake_agent_run(received_run_info):
        assert received_run_info is run_info
        yield json.dumps({"type": "tool", "content": "call"})
        yield json.dumps(
            {
                "type": "nl2a",
                "content": json.dumps(
                    {
                        "status": "success",
                        "recommendation_count": 0,
                        "recommendations": [],
                    }
                ),
            }
        )
        yield json.dumps({"type": "execution_logs", "content": "must be hidden"})
        yield json.dumps({"type": "nl2a", "content": "must also be hidden"})

    mocker.patch(
        "services.nl2agent_service.agent_run",
        side_effect=fake_agent_run,
    )
    request = NL2AgentRunRequest(query="Build a weather agent", agent_id=42)

    stream = await create_nl2agent_stream(
        request,
        "tenant-a",
        "en",
        "Bearer tenant-token",
    )
    chunks = [chunk async for chunk in stream]

    build_run_info.assert_awaited_once_with(
        request=request,
        tenant_id="tenant-a",
        language="en",
        authorization="Bearer tenant-token",
    )
    assert chunks == [
        'data: {"type": "tool", "content": "call"}\n\n',
        (
            'data: {"type": "nl2a", '
            '"content": "{\\"status\\": \\"success\\", '
            '\\"recommendation_count\\": 0, \\"recommendations\\": []}"}\n\n'
        ),
    ]
    run_info.stop_event.set.assert_called_once_with()


@pytest.mark.asyncio
async def test_create_stream_yields_process_chunks_without_waiting_for_later_output(
    mocker,
):
    run_info = MagicMock()
    run_info.stop_event = MagicMock()
    mocker.patch(
        "services.nl2agent_service.build_nl2agent_run_info",
        new_callable=AsyncMock,
        return_value=run_info,
    )
    process_chunks = [
        {"type": "step_count", "content": "1"},
        {"type": "model_output_thinking", "content": "reason"},
        {"type": "model_output_deep_thinking", "content": "deeper reason"},
        {"type": "model_output_code", "content": "code"},
        {"type": "parse", "content": "parsed"},
        {"type": "tool", "content": "call"},
        {"type": "execution_logs", "content": "observation"},
        {
            "type": "nl2a_state",
            "content": json.dumps(
                {
                    "event": "agent_draft_fields_saved",
                    "agent_id": 42,
                    "updated_fields": ["duty_prompt"],
                }
            ),
        },
        {
            "type": "nl2a_state",
            "content": json.dumps(
                {
                    "event": "agent_generation_completed",
                    "agent_id": 42,
                }
            ),
        },
        {"type": "final_answer", "content": "plain answer"},
    ]
    release_next = [asyncio.Event() for _ in process_chunks]

    async def gated_agent_run(_run_info):
        for payload, gate in zip(process_chunks, release_next, strict=True):
            yield json.dumps(payload)
            await gate.wait()

    mocker.patch(
        "services.nl2agent_service.agent_run",
        side_effect=gated_agent_run,
    )
    stream = await create_nl2agent_stream(
        NL2AgentRunRequest(query="Build an assistant", agent_id=42),
        "tenant-a",
        "en",
        None,
    )

    for expected, gate in zip(process_chunks, release_next, strict=True):
        chunk = await asyncio.wait_for(anext(stream), timeout=0.5)
        assert json.loads(chunk.removeprefix("data: ").strip()) == expected
        gate.set()

    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    run_info.stop_event.set.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "The configuration still needs user input.",
        "Run Agent Error: Model main_model not found",
    ],
)
async def test_create_stream_preserves_final_answers_without_fallback(mocker, content):
    run_info = MagicMock()
    run_info.stop_event = MagicMock()
    mocker.patch(
        "services.nl2agent_service.build_nl2agent_run_info",
        new_callable=AsyncMock,
        return_value=run_info,
    )

    async def final_answer_agent_run(_run_info):
        yield json.dumps({"type": "final_answer", "content": content})

    mocker.patch(
        "services.nl2agent_service.agent_run",
        side_effect=final_answer_agent_run,
    )
    stream = await create_nl2agent_stream(
        NL2AgentRunRequest(query="Build an assistant", agent_id=42),
        "tenant-a",
        "en",
        None,
    )

    chunks = [chunk async for chunk in stream]

    assert len(chunks) == 1
    assert json.loads(chunks[0].removeprefix("data: ").strip()) == {
        "type": "final_answer",
        "content": content,
    }


@pytest.mark.asyncio
async def test_create_stream_ends_without_synthesizing_nl2a_fallback(mocker):
    run_info = MagicMock()
    run_info.stop_event = MagicMock()
    mocker.patch(
        "services.nl2agent_service.build_nl2agent_run_info",
        new_callable=AsyncMock,
        return_value=run_info,
    )

    async def no_action_agent_run(_run_info):
        yield json.dumps({"type": "model_output_thinking", "content": "reason"})

    mocker.patch(
        "services.nl2agent_service.agent_run",
        side_effect=no_action_agent_run,
    )
    stream = await create_nl2agent_stream(
        NL2AgentRunRequest(query="Build an assistant", agent_id=42),
        "tenant-a",
        "en",
        None,
    )

    chunks = [chunk async for chunk in stream]

    assert [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks] == [
        {"type": "model_output_thinking", "content": "reason"}
    ]


@pytest.mark.asyncio
async def test_create_stream_hides_runtime_errors_and_stops_run(mocker):
    run_info = MagicMock()
    run_info.stop_event = MagicMock()
    mocker.patch(
        "services.nl2agent_service.build_nl2agent_run_info",
        new_callable=AsyncMock,
        return_value=run_info,
    )

    async def failing_agent_run(_run_info):
        if False:
            yield "unreachable"
        raise RuntimeError("private provider credentials")

    mocker.patch(
        "services.nl2agent_service.agent_run",
        side_effect=failing_agent_run,
    )

    stream = await create_nl2agent_stream(
        NL2AgentRunRequest(query="Build an assistant", agent_id=42),
        "tenant-a",
        "en",
        "Bearer tenant-token",
    )
    chunks = [chunk async for chunk in stream]

    assert len(chunks) == 1
    payload = json.loads(chunks[0].removeprefix("data: ").strip())
    assert payload == {
        "type": "error",
        "content": "NL2Agent execution failed.",
    }
    assert "credentials" not in chunks[0]
    assert "tenant-token" not in chunks[0]
    run_info.stop_event.set.assert_called_once_with()


@pytest.mark.asyncio
async def test_create_stream_propagates_cancellation_and_stops_run(mocker):
    run_info = MagicMock()
    run_info.stop_event = MagicMock()
    mocker.patch(
        "services.nl2agent_service.build_nl2agent_run_info",
        new_callable=AsyncMock,
        return_value=run_info,
    )

    async def cancelled_agent_run(_run_info):
        if False:
            yield "unreachable"
        raise asyncio.CancelledError

    mocker.patch(
        "services.nl2agent_service.agent_run",
        side_effect=cancelled_agent_run,
    )

    stream = await create_nl2agent_stream(
        NL2AgentRunRequest(query="Build an assistant", agent_id=42),
        "tenant-a",
        "en",
        None,
    )
    with pytest.raises(asyncio.CancelledError):
        await anext(stream)

    run_info.stop_event.set.assert_called_once_with()
