# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
import sys
import types
from threading import Event
from unittest.mock import AsyncMock, MagicMock

import pytest
from nexent.core.agents.context import ContextItemInput, ContextItemType
from nexent.core.models.capacity_budget import (
    ContextBudgetSnapshot,
    compute_context_budget_fingerprint,
)
from nexent.core.utils.observer import ProcessType
from pydantic import ValidationError

from management.services.agent.nl2agent import (
    Nl2AgentCompletionError,
    Nl2AgentDraftSaveError,
    Nl2AgentResourceError,
    _build_verified_bound_resources_context,
    _load_internal_uninstalled_resource_catalog,
    _load_installed_resource_catalog,
    _normalize_skill_config,
    _normalize_tool_config,
    _redact_installation_snapshot,
    _resource_similarity,
    recommend_installed_resources_impl,
    recommend_resources_impl,
    recommend_uninstalled_resources_impl,
    save_agent_draft_fields_impl,
    search_installed_resources_impl,
    search_uninstalled_resources_impl,
    search_installed_mcp_tools_by_query,
    validate_agent_generation_complete_impl,
)
from runtime.agentos.prepared_agent_creator import _Nl2AgentBoundaryObserver
from management.services.agent.nl2agent_tools import (
    AgentDraftFields,
    NL2A_MCP_LEGACY_TOOL_NAMES,
    NL2A_MCP_TOOL_NAMES,
    ResourceCandidate,
    ResourceRequirement,
)


def _context_budget_snapshot() -> ContextBudgetSnapshot:
    values = {
        "resolver_version": "2.0.0",
        "w1_fingerprint": "capacity-fingerprint",
        "provider": "openai",
        "model_name": "gpt-4o",
        "requested_output_tokens": 2768,
        "output_reserve_source": "model_default",
        "uncertainty_reserve_tokens": 0,
        "uncertainty_reserve_basis": "none",
        "approved_profile_reserve_tokens": None,
        "effective_input_limit_tokens": 30000,
        "compaction_trigger_ratio": 0.8,
        "compaction_trigger_ratio_source": "code_default",
        "compaction_trigger_threshold_tokens": 24000,
        "compaction_target_ratio": 0.6,
        "compaction_target_ratio_source": "code_default",
        "compaction_target_tokens": 18000,
        "field_sources": {},
        "warnings": [],
    }
    return ContextBudgetSnapshot(
        **values,
        fingerprint=compute_context_budget_fingerprint(**values),
    )


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
    """UT-BE-NCR-013: the first valid interactive card stops generation."""
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
        ProcessType.WARNING,
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
        "management.services.agent.authorization.query_agent_records_for_nl2agent",
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
        "management.services.agent.authorization.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    update_fields = mocker.patch(
        "management.services.agent.nl2agent.update_agent_draft_fields",
        return_value=1,
    )

    result = save_agent_draft_fields_impl(
        agent_id=22,
        fields=AgentDraftFields(
            prompt="Updated duty",
            example_questions=[],
        ),
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert result["created"] is False
    assert result["updated_fields"] == ["prompt", "example_questions"]
    update_fields.assert_called_once_with(
        agent_id=22,
        tenant_id="tenant-a",
        fields={"prompt": "Updated duty", "example_questions": []},
    )


def test_update_agent_draft_initializes_generated_name_once(mocker):
    mocker.patch(
        "management.services.agent.authorization.query_agent_records_for_nl2agent",
        return_value=[
            {
                "agent_id": 22,
                "tenant_id": "tenant-a",
                "version_no": 0,
                "delete_flag": "N",
                "created_by": "user-a",
                "name": None,
                "display_name": "Research Helper",
            }
        ],
    )
    mocker.patch(
        "management.services.agent.authorization.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    mocker.patch(
        "management.services.agent.nl2agent.query_all_agent_info_by_tenant_id",
        return_value=[{"agent_id": 22, "name": None}],
    )
    update_fields = mocker.patch(
        "management.services.agent.nl2agent.update_agent_draft_fields",
        return_value=1,
    )

    result = save_agent_draft_fields_impl(
        agent_id=22,
        fields=AgentDraftFields(name="research_assistant"),
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert result["updated_fields"] == ["name"]
    update_fields.assert_called_once_with(
        agent_id=22,
        tenant_id="tenant-a",
        fields={"name": "research_assistant"},
    )


def test_workbench_placeholder_can_be_named_from_user_requirements_once(mocker):
    mocker.patch(
        "management.services.agent.authorization.query_agent_records_for_nl2agent",
        return_value=[{
            "agent_id": 22, "tenant_id": "tenant-a", "version_no": 0,
            "delete_flag": "N", "created_by": "user-a", "name": None,
            "display_name": "Workbench Draft abc123-abcdef", "description": "",
        }],
    )
    mocker.patch(
        "management.services.agent.authorization.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    mocker.patch(
        "management.services.agent.nl2agent.query_all_agent_info_by_tenant_id",
        return_value=[{"agent_id": 22, "name": None}],
    )
    update_fields = mocker.patch(
        "management.services.agent.nl2agent.update_agent_draft_fields", return_value=1,
    )

    result = save_agent_draft_fields_impl(
        22,
        AgentDraftFields(name="customer_service_assistant", display_name="智能客服"),
        "tenant-a", "user-a",
    )

    assert result["updated_fields"] == ["name", "display_name"]
    update_fields.assert_called_once_with(
        agent_id=22, tenant_id="tenant-a",
        fields={"name": "customer_service_assistant", "display_name": "智能客服"},
    )


def test_nl2agent_cannot_rename_existing_display_name(mocker):
    mocker.patch(
        "management.services.agent.authorization.query_agent_records_for_nl2agent",
        return_value=[{
            "agent_id": 22, "tenant_id": "tenant-a", "version_no": 0,
            "delete_flag": "N", "created_by": "user-a", "name": None,
            "display_name": "Research Helper", "description": "",
        }],
    )
    mocker.patch(
        "management.services.agent.authorization.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    update_fields = mocker.patch("management.services.agent.nl2agent.update_agent_draft_fields")

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            22,
            AgentDraftFields(name="research_assistant", display_name="New Name"),
            "tenant-a", "user-a",
        )

    assert exc_info.value.code == "agent_display_name_immutable"
    update_fields.assert_not_called()


@pytest.mark.parametrize(
    ("draft_name", "existing_agents", "expected_code", "retryable"),
    [
        ("existing_assistant", [], "agent_name_already_set", False),
        (
            None,
            [{"agent_id": 99, "name": "research_assistant"}],
            "agent_name_duplicate",
            True,
        ),
    ],
)
def test_update_agent_draft_rejects_overwrite_or_duplicate_generated_name(
    mocker,
    draft_name,
    existing_agents,
    expected_code,
    retryable,
):
    mocker.patch(
        "management.services.agent.authorization.query_agent_records_for_nl2agent",
        return_value=[
            {
                "agent_id": 22,
                "tenant_id": "tenant-a",
                "version_no": 0,
                "delete_flag": "N",
                "created_by": "user-a",
                "name": draft_name,
            }
        ],
    )
    mocker.patch(
        "management.services.agent.authorization.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    mocker.patch(
        "management.services.agent.nl2agent.query_all_agent_info_by_tenant_id",
        return_value=existing_agents,
    )
    update_fields = mocker.patch(
        "management.services.agent.nl2agent.update_agent_draft_fields"
    )

    with pytest.raises(Nl2AgentDraftSaveError) as exc_info:
        save_agent_draft_fields_impl(
            22,
            AgentDraftFields(name="research_assistant"),
            "tenant-a",
            "user-a",
        )

    assert exc_info.value.code == expected_code
    assert exc_info.value.retryable is retryable
    update_fields.assert_not_called()


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
        "management.services.agent.authorization.query_agent_records_for_nl2agent",
        return_value=records,
    )
    mocker.patch(
        "management.services.agent.authorization.get_user_role_by_tenant",
        return_value=role,
    )
    update_fields = mocker.patch(
        "management.services.agent.nl2agent.update_agent_draft_fields"
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
        "management.services.agent.authorization.query_agent_records_for_nl2agent",
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
        "management.services.agent.authorization.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    mocker.patch(
        "management.services.agent.nl2agent.update_agent_draft_fields",
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
        "management.services.agent.authorization.query_agent_records_for_nl2agent",
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
        "management.services.agent.authorization.get_user_role_by_tenant",
        return_value="MEMBER",
    )
    mocker.patch(
        "management.services.agent.nl2agent.update_agent_draft_fields",
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


@pytest.mark.parametrize(
    "name",
    [123, True, [], {}],
)
def test_agent_draft_fields_reject_non_string_name(name):
    with pytest.raises(ValidationError):
        AgentDraftFields(name=name)


def test_search_filters_catalog_and_returns_safe_metadata(mocker):
    query_tools = mocker.patch(
        "management.services.agent.nl2agent.query_all_tools",
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
        "management.services.agent.nl2agent.query_all_tools",
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
    mocker.patch("management.services.agent.nl2agent.fuzz.WRatio", return_value=80)
    mocker.patch(
        "management.services.agent.nl2agent.fuzz.token_set_ratio",
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
        "management.services.agent.nl2agent.query_all_tools",
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
    mocker.patch("management.services.agent.nl2agent.fuzz.WRatio", return_value=44.9)
    mocker.patch(
        "management.services.agent.nl2agent.fuzz.token_set_ratio",
        return_value=20,
    )

    assert search_installed_mcp_tools_by_query(
        "tenant-a",
        "weather forecast search",
    ) == []


def test_search_skips_unsearchable_tools_and_sanitizes_malformed_inputs(mocker):
    mocker.patch(
        "management.services.agent.nl2agent.query_all_tools",
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
    mocker.patch("management.services.agent.nl2agent.fuzz.WRatio", return_value=90)
    mocker.patch("management.services.agent.nl2agent.fuzz.token_set_ratio", return_value=90)

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
        "management.services.tool.configuration.list_all_tools",
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
    mocker.patch(
        "management.services.agent.nl2agent.ENABLE_AIDP_KNOWLEDGE",
        False,
    )

    catalog = await _load_installed_resource_catalog(
        tenant_id="tenant-a",
        user_id="user-a",
    )
    catalog_by_name = {item["name"]: item for item in catalog}
    assert "wrapper" in catalog_by_name
    assert "knowledge_base_search" in catalog_by_name
    assert "aidp_search" not in catalog_by_name
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enable_aidp_knowledge", "expected_knowledge_tools"),
    [
        (True, {"aidp_search", "ind_aidp_search"}),
        (False, {"knowledge_base_search", "ind_aidp_search"}),
    ],
)
async def test_installed_resource_catalog_filters_knowledge_tools_by_deployment(
    mocker,
    enable_aidp_knowledge,
    expected_knowledge_tools,
):
    mocker.patch(
        "management.services.tool.configuration.list_all_tools",
        new=AsyncMock(
            return_value=[
                {
                    "tool_id": tool_id,
                    "name": name,
                    "description": "Knowledge search",
                    "source": "local",
                    "is_available": True,
                    "is_user_selectable": name == "ind_aidp_search",
                }
                for tool_id, name in enumerate(
                    (
                        "knowledge_base_search",
                        "ind_aidp_search",
                        "aidp_search",
                    ),
                    start=1,
                )
            ]
        ),
    )
    mocker.patch(
        "management.services.skill.service.SkillService.list_visible_skills",
        return_value=[],
    )
    mocker.patch(
        "management.services.agent.nl2agent.ENABLE_AIDP_KNOWLEDGE",
        enable_aidp_knowledge,
    )

    catalog = await _load_installed_resource_catalog(
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert {item["name"] for item in catalog} == expected_knowledge_tools


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
        'management.services.skill.transfer.get_official_skills_with_status',
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
        "management.services.repository.mcp.service.list_community_mcp_services",
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
        "management.services.agent.nl2agent._load_internal_uninstalled_resource_catalog",
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
        'management.services.skill.transfer.get_official_skills_with_status',
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
        "management.services.repository.mcp.service.list_community_mcp_services",
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
        "management.services.agent.nl2agent._load_internal_uninstalled_resource_catalog",
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
        "management.services.agent.nl2agent.recommend_installed_resources_impl",
        new=AsyncMock(return_value=installed_result),
    )
    uninstalled_resolver = mocker.patch(
        "management.services.agent.nl2agent.recommend_uninstalled_resources_impl",
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
        "management.services.agent.nl2agent._load_installed_resource_catalog",
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
        "management.services.agent.nl2agent.query_all_enabled_tool_instances",
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
        "management.services.agent.nl2agent._load_installed_resource_catalog",
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
        "management.services.agent.nl2agent.query_all_enabled_tool_instances",
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
        "management.services.agent.nl2agent.require_agent_draft_edit",
        return_value={
            "name": "current_assistant",
            "description": "Current authoritative description",
            "business_description": "Legacy workflow description",
        },
    )
    mocker.patch(
        "management.services.agent.nl2agent._load_installed_resource_catalog",
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
        "management.services.agent.nl2agent.query_all_enabled_tool_instances",
        return_value=[{"tool_id": 7, "params": {"api_key": "private-secret"}}],
    )
    mocker.patch(
        "management.services.agent.nl2agent.query_enabled_skill_instances",
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
        "prompt": "Verify sources and produce a report.",
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
        "management.services.agent.nl2agent._load_verified_nl2agent_state",
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
@pytest.mark.parametrize("facts", [[], [{"resource_type": "tool", "resource_id": 7, "name": "search"}]])
async def test_validate_agent_generation_complete_allows_empty_resource_prompts(
    mocker, facts,
):
    mocker.patch(
        "management.services.agent.nl2agent._load_verified_nl2agent_state",
        new_callable=AsyncMock,
        return_value=(
            {
                "name": "writing_assistant",
                "display_name": "Writing Assistant",
                "description": "Improve writing",
                "prompt": "Help users improve their writing.",
                "greeting_message": "Hello, what should we write?",
                "example_questions": ["Improve this paragraph"],
            },
            facts,
        ),
    )

    await validate_agent_generation_complete_impl(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", [None, "", "   "])
async def test_validate_agent_generation_complete_rejects_incomplete_resource_prompts(
    mocker, prompt,
):
    mocker.patch(
        "management.services.agent.nl2agent._load_verified_nl2agent_state",
        new_callable=AsyncMock,
        return_value=(
            {
                "name": "research_assistant",
                "display_name": "Research Assistant",
                "description": "Research help",
                "prompt": prompt,
                "constraint_prompt": "Use search.",
                "few_shots_prompt": "A valid legacy example",
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
    assert exc_info.value.failed_fields == ["prompt"]


@pytest.mark.asyncio
async def test_validate_agent_generation_complete_requires_description(mocker):
    mocker.patch(
        "management.services.agent.nl2agent._load_verified_nl2agent_state",
        new_callable=AsyncMock,
        return_value=({"name": "draft_assistant", "description": " "}, []),
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
async def test_validate_agent_generation_complete_requires_generated_name(mocker):
    mocker.patch(
        "management.services.agent.nl2agent._load_verified_nl2agent_state",
        new_callable=AsyncMock,
        return_value=({"display_name": "Draft", "description": "Ready"}, []),
    )

    with pytest.raises(Nl2AgentCompletionError) as exc_info:
        await validate_agent_generation_complete_impl(
            agent_id=42,
            tenant_id="tenant-a",
            user_id="user-a",
        )

    assert exc_info.value.code == "draft_fields_incomplete"
    assert exc_info.value.failed_fields == ["name"]
