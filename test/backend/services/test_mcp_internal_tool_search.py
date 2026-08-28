import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from mcp.types import Tool
from pydantic import ValidationError

import services.nl2agent_service as nl2agent_service
import services.tool_configuration_service as tool_configuration_service
import tool_collection.mcp.nl2agent_mcp_tools as nl2agent_mcp_tools_module
from services.agent_draft_permission_service import AgentDraftEditError
from services.tool_configuration_service import get_tool_from_remote_mcp_server
from tool_collection.mcp.local_mcp_service import (
    LOCAL_MCP_TOOL_NAME_OVERRIDES,
    local_mcp_service,
)
from tool_collection.mcp.nl2agent_mcp_service import (
    nl2agent_mcp_service,
)
from tool_collection.mcp.nl2agent_mcp_tools import (
    NL2AGENT_AGENT_ID_HEADER,
    NL2AGENT_MCP_TOOL_META,
    NL2A_MCP_LOCAL_TOOL_NAMES,
    NL2A_MCP_SERVICE_NAME,
    NL2A_MCP_TOOL_NAMES,
    NL2A_WRAPPER_DESCRIPTION,
    NL2A_WRAPPER_LOCAL_NAME,
    NL2A_WRAPPER_NAME,
    InstalledResourceBindingPayload,
    RecommendResourcesOutput,
    RECOMMEND_RESOURCES_DESCRIPTION,
    RECOMMEND_RESOURCES_LOCAL_NAME,
    RECOMMEND_RESOURCES_NAME,
    RequirementClarificationQuestion,
    SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION,
    SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME,
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    SEARCH_INSTALLED_RESOURCES_DESCRIPTION,
    SEARCH_INSTALLED_RESOURCES_LOCAL_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SEARCH_UNINSTALLED_RESOURCES_DESCRIPTION,
    SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
    SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION,
    SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    SearchUninstalledResourcesInput,
    SuggestedResourceInstallationPayload,
    build_nl2a_wrapper,
    nl2a_wrapper,
    recommend_resources,
    save_agent_draft_fields,
    search_installed_mcp_tools,
    search_installed_resources,
    search_uninstalled_resources,
)


def _unwrap_nl2a(result: str) -> dict:
    wrapper, marker = result.rsplit("</nl2a>", 1)
    assert marker.strip() == "NL2A payload generated."
    return json.loads(wrapper.split("<nl2a>", 1)[1])


@pytest.mark.asyncio
async def test_mcp_search_is_tenant_scoped_sorted_and_safe(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer tenant-token"}),
    )
    get_current_user_id = mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    query_all_tools = mocker.patch.object(
        nl2agent_service,
        "query_all_tools",
        return_value=[
            {
                "tool_id": 12,
                "name": "secondary_weather",
                "origin_name": "secondary-weather",
                "description": "Secondary weather forecast search",
                "source": "mcp",
                "usage": "weather-server-b",
                "labels": ["weather"],
                "inputs": '{"city":"string"}',
                "is_available": True,
                "params": {"token": "must-not-leak"},
            },
            {
                "tool_id": 7,
                "name": "primary_weather",
                "origin_name": "primary-weather",
                "description": """Primary weather forecast search
                    with hourly rain probability""",
                "source": "mcp",
                "usage": "weather-server-a",
                "labels": ["weather", "forecast"],
                "inputs": (
                    "{'city': {'type': 'string', 'description': "
                    "\"The city name,\\n translated to English when it isn't English.\"}, "
                    "'include_forecast': {'type': 'boolean', 'default': False}}"
                ),
                "is_available": True,
                "request_headers": {"Authorization": "must-not-leak"},
            },
            {
                "tool_id": 8,
                "name": "disabled_weather",
                "description": "Weather forecast search",
                "source": "mcp",
                "usage": "weather-server-a",
                "is_available": False,
            },
            {
                "tool_id": 9,
                "name": "local_weather",
                "description": "Weather forecast search",
                "source": "local",
                "usage": "local",
                "is_available": True,
            },
        ],
    )

    def score_by_document(_query, document):
        return 95 if "primary_weather" in document else 75

    mocker.patch.object(
        nl2agent_service.fuzz,
        "WRatio",
        side_effect=score_by_document,
    )
    mocker.patch.object(
        nl2agent_service.fuzz,
        "token_set_ratio",
        side_effect=score_by_document,
    )

    result = await search_installed_mcp_tools(
        [" Weather ", "forecast", "WEATHER"]
    )

    get_current_user_id.assert_called_once_with("Bearer tenant-token")
    query_all_tools.assert_called_once_with(tenant_id="tenant-a")
    assert {
        call.args[0]
        for call in nl2agent_service.fuzz.WRatio.call_args_list
    } == {"weather forecast"}
    assert {
        call.args[0]
        for call in nl2agent_service.fuzz.token_set_ratio.call_args_list
    } == {"weather forecast"}
    assert result["status"] == "success"
    assert result["recommendation_count"] == 2
    assert set(result) == {
        "subtype",
        "status",
        "recommendation_count",
        "recommendations",
    }
    assert result["subtype"] == "local_mcp_recommendation"
    assert [item["tool_id"] for item in result["recommendations"]] == [7, 12]
    assert result["recommendations"][0] == {
        "tool_id": 7,
        "name": "primary_weather",
        "origin_name": "primary-weather",
        "description": (
            "Primary weather forecast search with hourly rain probability"
        ),
        "source": "mcp",
        "usage": "weather-server-a",
        "labels": ["weather", "forecast"],
        "inputs": {
            "city": {
                "type": "string",
                "description": (
                    "The city name, translated to English when it isn't English."
                ),
            },
            "include_forecast": {
                "type": "boolean",
                "default": False,
            },
        },
        "score": 0.95,
    }
    safe_fields = {
        "tool_id",
        "name",
        "origin_name",
        "description",
        "source",
        "usage",
        "labels",
        "inputs",
        "score",
    }
    assert all(set(item) == safe_fields for item in result["recommendations"])
    assert "must-not-leak" not in json.dumps(result)


@pytest.mark.asyncio
async def test_mcp_search_returns_sanitized_contract_errors(mocker):
    for keywords in ([], ["   "]):
        invalid_result = await search_installed_mcp_tools(keywords)
        assert invalid_result == {
            "subtype": "local_mcp_recommendation",
            "status": "error",
            "code": "invalid_keywords",
            "retryable": True,
        }

    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer private-token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "search_installed_mcp_tools_by_query",
        side_effect=RuntimeError("private database details"),
    )

    result = await search_installed_mcp_tools(["private", "weather"])

    assert result == {
        "subtype": "local_mcp_recommendation",
        "status": "error",
        "code": "tool_search_failed",
        "retryable": True,
    }
    serialized_result = json.dumps(result)
    assert "private-token" not in serialized_result
    assert "private database details" not in serialized_result


@pytest.mark.asyncio
async def test_nl2agent_mcp_service_owns_only_nl2agent_tools():
    registered_tools = await nl2agent_mcp_service.get_tools()

    assert nl2agent_mcp_service.name == NL2A_MCP_SERVICE_NAME
    assert set(registered_tools) == set(NL2A_MCP_LOCAL_TOOL_NAMES)
    assert all(
        tool.meta == NL2AGENT_MCP_TOOL_META
        for tool in registered_tools.values()
    )


@pytest.mark.asyncio
async def test_mcp_search_registration_has_stable_name_schema_and_marker():
    local_tools = await local_mcp_service.get_tools()
    parent = FastMCP("test-parent")
    parent.mount(
        local_mcp_service,
        local_mcp_service.name,
        tool_names=LOCAL_MCP_TOOL_NAME_OVERRIDES,
    )
    mounted_tools = await parent.get_tools()
    tool = mounted_tools[SEARCH_INSTALLED_MCP_TOOLS_NAME]
    resource_search_tool = mounted_tools[SEARCH_INSTALLED_RESOURCES_NAME]
    uninstalled_search_tool = mounted_tools[SEARCH_UNINSTALLED_RESOURCES_NAME]
    recommend_tool = mounted_tools[RECOMMEND_RESOURCES_NAME]
    wrapper_tool = mounted_tools[NL2A_WRAPPER_NAME]
    save_tool = mounted_tools[SAVE_AGENT_DRAFT_FIELDS_NAME]

    assert LOCAL_MCP_TOOL_NAME_OVERRIDES == {
        name: name
        for name in NL2A_MCP_TOOL_NAMES
    }
    assert set(local_tools) == {
        *NL2A_MCP_TOOL_NAMES,
        "test_tool_name",
    }
    assert set(mounted_tools) == {
        *NL2A_MCP_TOOL_NAMES,
        "local_test_tool_name",
    }
    assert SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME not in local_tools
    assert SEARCH_INSTALLED_RESOURCES_LOCAL_NAME not in local_tools
    assert SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME not in local_tools
    assert RECOMMEND_RESOURCES_LOCAL_NAME not in local_tools
    assert SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME not in local_tools
    assert f"local_{SEARCH_INSTALLED_MCP_TOOLS_NAME}" not in mounted_tools
    assert tool.name == SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME
    assert set(tool.parameters["properties"]) == {"keywords"}
    assert tool.parameters["properties"]["keywords"]["type"] == "array"
    assert tool.parameters["properties"]["keywords"]["items"]["type"] == "string"
    assert tool.parameters["required"] == ["keywords"]
    assert tool.meta == NL2AGENT_MCP_TOOL_META
    assert "print(result)" in tool.description
    assert tool.description == SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION
    assert resource_search_tool.description == SEARCH_INSTALLED_RESOURCES_DESCRIPTION
    assert resource_search_tool.name == SEARCH_INSTALLED_RESOURCES_LOCAL_NAME
    assert set(resource_search_tool.parameters["properties"]) == {
        "requirements",
        "agent_id",
    }
    assert resource_search_tool.parameters["required"] == [
        "agent_id",
        "requirements",
    ]
    assert uninstalled_search_tool.description == (
        SEARCH_UNINSTALLED_RESOURCES_DESCRIPTION
    )
    assert uninstalled_search_tool.name == SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME
    assert set(uninstalled_search_tool.parameters["properties"]) == {
        "agent_id",
        "requirements",
        "exclude_refs",
    }
    assert recommend_tool.description == RECOMMEND_RESOURCES_DESCRIPTION
    assert recommend_tool.name == RECOMMEND_RESOURCES_LOCAL_NAME
    assert set(recommend_tool.parameters["properties"]) == {
        "candidates",
        "recommended_refs",
        "agent_id",
    }
    assert recommend_tool.parameters["required"] == [
        "agent_id",
        "candidates",
        "recommended_refs",
    ]
    assert wrapper_tool.name == NL2A_WRAPPER_LOCAL_NAME
    assert wrapper_tool.description == NL2A_WRAPPER_DESCRIPTION
    assert wrapper_tool.meta == NL2AGENT_MCP_TOOL_META
    assert save_tool.description == SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION
    assert save_tool.name == SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME
    assert save_tool.parameters["required"] == ["agent_id", "fields"]
    assert set(save_tool.parameters["properties"]) == {"agent_id", "fields"}
    assert wrapper_tool.parameters["required"] == ["subtype", "agent_id"]
    assert set(wrapper_tool.parameters["properties"]) == {
        "subtype",
        "agent_id",
        "resource_result",
        "questions",
    }
    assert wrapper_tool.parameters["properties"]["subtype"]["enum"] == [
        "requirement_clarification",
        "suggested_resource_installation",
        "installed_resource_binding",
    ]
    assert wrapper_tool.meta["nexent_internal"] is True


def test_uninstalled_resource_models_reject_invalid_identifiers_and_options():
    requirement = {"requirement_id": "lookup", "query": "Search data"}
    with pytest.raises(ValidationError, match="requirement_id values must be unique"):
        SearchUninstalledResourcesInput(
            requirements=[requirement, requirement],
        )

    for exclude_refs in (
        ["tenant_skill_repository:1", "tenant_skill_repository:1"],
        ["   "],
    ):
        with pytest.raises(
            ValidationError,
            match="exclude_refs must be non-empty and unique",
        ):
            SearchUninstalledResourcesInput(
                requirements=[requirement],
                exclude_refs=exclude_refs,
            )

    candidate = {
        "candidate_ref": "tenant_skill_repository:1",
        "resource_type": "skill",
        "source": "TENANT_SKILL_REPOSITORY",
        "name": "tenant-skill",
        "requirement_ids": ["lookup"],
        "score": 0.9,
    }
    option = {
        "option_id": "repository",
        "label": "Install",
        "form_kind": "SKILL_CONFIG",
        "config": [],
    }

    invalid_resources = [
        {
            "candidate": candidate,
            "recommendation": "recommended",
            "form_kind": "SKILL_CONFIG",
            "config": [],
            "installation_options": [option, option],
            "default_option_id": "repository",
        },
        {
            "candidate": candidate,
            "recommendation": "recommended",
            "form_kind": "SKILL_CONFIG",
            "config": [],
            "installation_options": [option],
            "default_option_id": "missing",
        },
        {
            "candidate": candidate,
            "recommendation": "recommended",
            "form_kind": "SKILL_CONFIG",
            "config": [],
            "installation_options": [],
            "default_option_id": "repository",
        },
    ]
    for resource in invalid_resources:
        with pytest.raises(ValidationError):
            RecommendResourcesOutput.model_validate({
                "status": "success",
                "resources": [resource],
            })


def test_resource_card_payloads_reject_wrong_availability():
    installed_resource = {
        "candidate": {
            "candidate_ref": "tool:7",
            "resource_type": "tool",
            "source": "LOCAL_TOOL",
            "name": "search",
            "requirement_ids": ["lookup"],
            "score": 0.9,
        },
        "recommendation": "recommended",
        "form_kind": "TOOL_CONFIG",
        "config": [],
    }
    uninstalled_resource = {
        "candidate": {
            "candidate_ref": "tenant_skill_repository:1",
            "resource_type": "skill",
            "source": "TENANT_SKILL_REPOSITORY",
            "name": "tenant-skill",
            "requirement_ids": ["lookup"],
            "score": 0.9,
        },
        "recommendation": "recommended",
        "form_kind": "SKILL_CONFIG",
        "config": [],
        "installation_options": [{
            "option_id": "repository",
            "label": "Install",
            "form_kind": "SKILL_CONFIG",
            "config": [],
        }],
        "default_option_id": "repository",
    }

    with pytest.raises(ValidationError, match="already be installed"):
        InstalledResourceBindingPayload(
            agent_id=42,
            resources=[uninstalled_resource],
        )
    with pytest.raises(ValidationError, match="must be installable"):
        SuggestedResourceInstallationPayload(
            agent_id=42,
            resources=[installed_resource],
        )


def test_build_resource_wrapper_requires_result_and_supported_subtype():
    with pytest.raises(ValueError, match="requires agent_id and resource_result"):
        build_nl2a_wrapper(
            subtype="suggested_resource_installation",
            agent_id=42,
        )
    with pytest.raises(ValueError, match="unsupported nl2a subtype"):
        build_nl2a_wrapper(
            subtype="unsupported",  # type: ignore[arg-type]
            agent_id=42,
        )


@pytest.mark.asyncio
async def test_save_agent_draft_fields_emits_saved_fields_state(
    mocker,
):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    save_impl = mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        return_value={
            "status": "success",
            "agent_id": 1042,
            "created": False,
            "updated_fields": [
                "description",
            ],
        },
    )
    fields = {
        "description": "Researches a topic.",
    }

    result = await save_agent_draft_fields(1042, fields)

    result_json, state_wrapper = result.split("\n", 1)
    assert json.loads(result_json) == {
        "status": "success",
        "agent_id": 1042,
        "created": False,
        "updated_fields": [
            "description",
        ],
    }
    assert json.loads(
        state_wrapper.removeprefix("<nl2a_state>").removesuffix("</nl2a_state>")
    ) == {
        "event": "agent_draft_fields_saved",
        "agent_id": 1042,
        "updated_fields": ["description"],
    }
    assert "agent_draft_created" not in result
    save_impl.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent_id", "fields"),
    [
        (None, {"description": "Missing ID"}),
        (1042, {"name": "renamed_agent"}),
        (1042, {"display_name": "Renamed Agent"}),
        (1042, {"business_description": "Removed field"}),
        (1042, {}),
    ],
)
async def test_save_agent_draft_fields_rejects_missing_id_and_forbidden_fields(
    mocker,
    agent_id,
    fields,
):
    save_impl = mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
    )

    result = json.loads(await save_agent_draft_fields(agent_id, fields))

    assert result["code"] == "invalid_agent_fields"
    assert result["created"] is False
    save_impl.assert_not_called()


@pytest.mark.asyncio
async def test_save_agent_draft_fields_emits_prompt_failure_state(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        side_effect=nl2agent_service.Nl2AgentDraftSaveError(
            "draft_save_failed",
            retryable=True,
        ),
    )

    result_json, state_wrapper = (
        await save_agent_draft_fields(1042, {"duty_prompt": "Research"})
    ).split("\n", 1)

    assert json.loads(result_json)["code"] == "draft_save_failed"
    assert json.loads(
        state_wrapper.removeprefix("<nl2a_state>").removesuffix("</nl2a_state>")
    ) == {
        "event": "prompt_generation_failed",
        "agent_id": 1042,
        "failed_fields": ["duty_prompt"],
    }


@pytest.mark.asyncio
async def test_save_agent_draft_fields_reuses_trusted_context_across_rounds(mocker):
    request = SimpleNamespace(
        headers={
            "Authorization": "Bearer token",
            NL2AGENT_AGENT_ID_HEADER: "1042",
        }
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=request,
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )

    def save_impl(*, agent_id, fields, tenant_id, user_id):
        return {
            "status": "success",
            "agent_id": 1042,
            "created": False,
            "updated_fields": list(fields.model_fields_set),
        }

    save = mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        side_effect=save_impl,
    )
    validate_complete = mocker.patch.object(
        nl2agent_service,
        "validate_agent_generation_complete_impl",
        new=AsyncMock(),
    )
    first = await save_agent_draft_fields(1042, {"description": "Updated"})
    second = await save_agent_draft_fields(
        1042,
        {"duty_prompt": "Verify sources"},
    )

    assert [call.kwargs["agent_id"] for call in save.call_args_list] == [1042, 1042]
    first_result, first_state = first.split("\n", 1)
    second_result, second_state = second.split("\n", 1)
    assert json.loads(first_result)["created"] is False
    assert json.loads(second_result)["created"] is False
    assert json.loads(
        first_state.removeprefix("<nl2a_state>").removesuffix("</nl2a_state>")
    )["updated_fields"] == ["description"]
    assert json.loads(
        second_state.removeprefix("<nl2a_state>").removesuffix("</nl2a_state>")
    ) == {
        "event": "agent_generation_completed",
        "agent_id": 1042,
    }
    validate_complete.assert_awaited_once_with(
        agent_id=1042,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
async def test_save_agent_draft_fields_rejects_context_mismatch_without_write(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(
            headers={
                "Authorization": "Bearer token",
                NL2AGENT_AGENT_ID_HEADER: "1042",
            }
        ),
    )
    save = mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
    )

    result = json.loads(
        await save_agent_draft_fields(1043, {"description": "Wrong draft"})
    )

    assert result == {
        "status": "error",
        "agent_id": 1043,
        "created": False,
        "updated_fields": [],
        "code": "agent_context_mismatch",
        "retryable": False,
    }
    save.assert_not_called()


@pytest.mark.asyncio
async def test_clarification_wrapper_keeps_trusted_agent_id(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(
            headers={
                "Authorization": "Bearer token",
                NL2AGENT_AGENT_ID_HEADER: "42",
            }
        ),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    require_edit = mocker.patch(
        "services.agent_draft_permission_service.require_agent_draft_edit"
    )

    wrapped = await nl2a_wrapper(
        subtype="requirement_clarification",
        agent_id=42,
        questions=[
            RequirementClarificationQuestion(
                question_id="scope",
                question_type="text",
                title="What should the Agent cover?",
                required=True,
                options=[],
                allow_other=False,
                other_input_expanded=False,
            )
        ],
    )

    assert _unwrap_nl2a(wrapped)["agent_id"] == 42
    require_edit.assert_called_once_with(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
async def test_resource_tools_reject_invalid_model_echoes_without_service_calls(
    mocker,
):
    search_impl = mocker.patch.object(
        nl2agent_service,
        "search_installed_resources_impl",
    )
    uninstalled_impl = mocker.patch.object(
        nl2agent_service,
        "search_uninstalled_resources_impl",
    )
    recommend_impl = mocker.patch.object(
        nl2agent_service,
        "recommend_resources_impl",
    )

    search_result = await search_installed_resources(agent_id=42, requirements=[])
    uninstalled_result = await search_uninstalled_resources(
        agent_id=42,
        requirements=[],
        exclude_refs=[],
    )
    recommend_result = await recommend_resources(
        agent_id=42,
        candidates=[
            {
                "candidate_ref": "tool:7",
                "resource_type": "tool",
                "source": "LOCAL_TOOL",
                "name": "search",
                "requirement_ids": ["lookup"],
                "score": 0.9,
            }
        ],
        recommended_refs=["tool:99"],
    )

    assert search_result["code"] == "invalid_requirements"
    assert uninstalled_result["code"] == "invalid_requirements"
    assert search_result["retryable"] is False
    assert recommend_result["code"] == "invalid_candidates"
    assert recommend_result["retryable"] is False
    search_impl.assert_not_called()
    uninstalled_impl.assert_not_called()
    recommend_impl.assert_not_called()


@pytest.mark.asyncio
async def test_uninstalled_search_rejects_cross_agent_context(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(
            headers={
                "Authorization": "Bearer token",
                NL2AGENT_AGENT_ID_HEADER: "41",
            }
        ),
    )
    search_impl = mocker.patch.object(
        nl2agent_service,
        "search_uninstalled_resources_impl",
    )

    result = await search_uninstalled_resources(
        agent_id=42,
        requirements=[{"requirement_id": "lookup", "query": "Search data"}],
    )

    assert result["code"] == "agent_context_mismatch"
    assert result["retryable"] is False
    search_impl.assert_not_called()


@pytest.mark.asyncio
async def test_uninstalled_search_returns_stable_permission_and_runtime_errors(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    require_edit = mocker.patch(
        "services.agent_draft_permission_service.require_agent_draft_edit"
    )
    search_impl = mocker.patch.object(
        nl2agent_service,
        "search_uninstalled_resources_impl",
        new=AsyncMock(),
    )
    call = {
        "agent_id": 42,
        "requirements": [{
            "requirement_id": "lookup",
            "query": "Search data",
        }],
    }

    require_edit.side_effect = AgentDraftEditError("agent_read_only")
    read_only = await search_uninstalled_resources(**call)
    assert read_only["code"] == "agent_read_only"
    assert read_only["retryable"] is False

    require_edit.side_effect = None
    search_impl.side_effect = PermissionError("private authorization details")
    unauthorized = await search_uninstalled_resources(**call)
    assert unauthorized["code"] == "unauthorized"
    assert "private" not in json.dumps(unauthorized)

    search_impl.side_effect = RuntimeError("private search details")
    failed = await search_uninstalled_resources(**call)
    assert failed["code"] == "resource_search_failed"
    assert failed["retryable"] is True
    assert "private" not in json.dumps(failed)


@pytest.mark.asyncio
async def test_resource_tools_return_tenant_scoped_results_and_stable_errors(
    mocker,
):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    get_user = mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    search_output = MagicMock()
    search_output.model_dump.return_value = {
        "status": "success",
        "candidates": [],
        "uncovered_requirement_ids": ["lookup"],
    }
    search_impl = mocker.patch.object(
        nl2agent_service,
        "search_installed_resources_impl",
        new=AsyncMock(return_value=search_output),
    )
    uninstalled_impl = mocker.patch.object(
        nl2agent_service,
        "search_uninstalled_resources_impl",
        new=AsyncMock(return_value=search_output),
    )
    recommend_output = MagicMock()
    recommend_output.model_dump.return_value = {
        "status": "success",
        "resources": [],
    }
    recommend_impl = mocker.patch.object(
        nl2agent_service,
        "recommend_resources_impl",
        new=AsyncMock(return_value=recommend_output),
    )
    mocker.patch(
        "services.agent_draft_permission_service.require_agent_draft_edit"
    )
    requirements = [{"requirement_id": "lookup", "query": "web search"}]
    candidate = {
        "candidate_ref": "tool:7",
        "resource_type": "tool",
        "source": "LOCAL_TOOL",
        "name": "search",
        "requirement_ids": ["lookup"],
        "score": 0.9,
    }

    assert (
        await search_installed_resources(agent_id=42, requirements=requirements)
    )["status"] == "success"
    assert (
        await search_uninstalled_resources(
            agent_id=42,
            requirements=requirements,
            exclude_refs=["tenant_mcp_repository:8"],
        )
    )["status"] == "success"
    assert (
        await recommend_resources(
            agent_id=42,
            candidates=[candidate],
            recommended_refs=["tool:7"],
        )
    )["status"] == "success"
    assert get_user.call_count == 3
    assert search_impl.await_args.kwargs["tenant_id"] == "tenant-a"
    assert "scope" not in uninstalled_impl.await_args.kwargs
    assert uninstalled_impl.await_args.kwargs["exclude_refs"] == [
        "tenant_mcp_repository:8"
    ]
    assert recommend_impl.await_args.kwargs["user_id"] == "user-a"
    assert recommend_impl.await_args.kwargs["agent_id"] == 42

    search_impl.side_effect = PermissionError("private auth details")
    assert (
        await search_installed_resources(agent_id=42, requirements=requirements)
    )["code"] == "unauthorized"
    search_impl.side_effect = RuntimeError("private search details")
    search_error = await search_installed_resources(
        agent_id=42,
        requirements=requirements,
    )
    assert search_error["code"] == "resource_search_failed"
    assert "private" not in json.dumps(search_error)

    recommend_impl.side_effect = nl2agent_service.Nl2AgentResourceError(
        "resource_not_visible"
    )
    assert (
        await recommend_resources(
            agent_id=42,
            candidates=[candidate],
            recommended_refs=["tool:7"],
        )
    )["code"] == "resource_not_visible"
    recommend_impl.side_effect = PermissionError("private auth details")
    assert (
        await recommend_resources(
            agent_id=42,
            candidates=[candidate],
            recommended_refs=["tool:7"],
        )
    )["code"] == "unauthorized"
    recommend_impl.side_effect = RuntimeError("private resolution details")
    resolution_error = await recommend_resources(
        agent_id=42,
        candidates=[candidate],
        recommended_refs=["tool:7"],
    )
    assert resolution_error["code"] == "resource_resolution_failed"
    assert "private" not in json.dumps(resolution_error)


@pytest.mark.asyncio
async def test_installed_binding_wrapper_rechecks_agent_and_candidates(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    require_edit = mocker.patch(
        "services.agent_draft_permission_service.require_agent_draft_edit"
    )
    resource_result = {
        "status": "success",
        "resources": [
            {
                "candidate": {
                    "candidate_ref": "tool:7",
                    "resource_type": "tool",
                    "source": "LOCAL_TOOL",
                    "name": "search",
                    "requirement_ids": ["lookup"],
                    "score": 0.9,
                },
                "recommendation": "recommended",
                "is_bound": True,
                "form_kind": "TOOL_CONFIG",
                "config": [],
            }
        ],
    }
    verified_result = {
        **resource_result,
        "resources": [
            {
                **resource_result["resources"][0],
                "is_bound": False,
            }
        ],
    }
    verified = RecommendResourcesOutput.model_validate(verified_result)
    recommend_impl = mocker.patch.object(
        nl2agent_service,
        "recommend_resources_impl",
        new=AsyncMock(return_value=verified),
    )

    wrapped = await nl2a_wrapper(
        subtype="installed_resource_binding",
        agent_id=42,
        resource_result=resource_result,
    )

    wrapped_resource = _unwrap_nl2a(wrapped)["resources"][0]
    assert wrapped_resource["candidate"]["name"] == "search"
    assert wrapped_resource["is_bound"] is False
    require_edit.assert_called_once_with(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )
    assert recommend_impl.await_args.kwargs["agent_id"] == 42
    assert recommend_impl.await_args.kwargs["recommended_refs"] == ["tool:7"]


@pytest.mark.asyncio
async def test_installation_wrapper_rechecks_agent_and_candidates(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch(
        "services.agent_draft_permission_service.require_agent_draft_edit"
    )
    resource_result = {
        "status": "success",
        "resources": [{
            "candidate": {
                "candidate_ref": "nexent_official_skill:daily-report",
                "resource_type": "skill",
                "source": "NEXENT_OFFICIAL_SKILL",
                "name": "daily-report",
                "requirement_ids": ["report"],
                "score": 0.9,
            },
            "recommendation": "recommended",
            "form_kind": "SKILL_CONFIG",
            "config": [],
            "installation_options": [{
                "option_id": "official",
                "label": "Install",
                "form_kind": "SKILL_CONFIG",
                "config": [],
            }],
            "default_option_id": "official",
        }],
    }
    verified = RecommendResourcesOutput.model_validate(resource_result)
    recommend_impl = mocker.patch.object(
        nl2agent_service,
        "recommend_resources_impl",
        new=AsyncMock(return_value=verified),
    )

    wrapped = await nl2a_wrapper(
        subtype="suggested_resource_installation",
        agent_id=42,
        resource_result=resource_result,
    )

    payload = _unwrap_nl2a(wrapped)
    assert payload["subtype"] == "suggested_resource_installation"
    assert payload["resources"][0]["default_option_id"] == "official"
    assert payload["resources"][0]["is_bound"] is False
    assert recommend_impl.await_args.kwargs["agent_id"] == 42
    assert recommend_impl.await_args.kwargs["recommended_refs"] == [
        "nexent_official_skill:daily-report"
    ]


@pytest.mark.asyncio
async def test_resource_wrapper_rejects_missing_results_and_wrong_sources(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch(
        "services.agent_draft_permission_service.require_agent_draft_edit"
    )

    with pytest.raises(ValueError, match="requires agent_id and resource_result"):
        await nl2a_wrapper(
            subtype="suggested_resource_installation",
            agent_id=42,
        )

    installed_result = {
        "status": "success",
        "resources": [{
            "candidate": {
                "candidate_ref": "tool:7",
                "resource_type": "tool",
                "source": "LOCAL_TOOL",
                "name": "search",
                "requirement_ids": ["lookup"],
                "score": 0.9,
            },
            "recommendation": "recommended",
            "form_kind": "TOOL_CONFIG",
            "config": [],
        }],
    }
    with pytest.raises(
        ValueError,
        match="invalid resources for suggested_resource_installation",
    ):
        await nl2a_wrapper(
            subtype="suggested_resource_installation",
            agent_id=42,
            resource_result=installed_result,
        )
    with pytest.raises(
        ValueError,
        match="invalid resources for installed_resource_binding",
    ):
        await nl2a_wrapper(
            subtype="installed_resource_binding",
            agent_id=42,
            resource_result={"status": "success", "resources": []},
        )


@pytest.mark.asyncio
async def test_final_prompt_batch_emits_generation_completed_state(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    save_impl = mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        return_value={
            "status": "success",
            "agent_id": 42,
            "created": False,
            "updated_fields": ["greeting_message", "example_questions"],
        },
    )
    validate_complete = mocker.patch.object(
        nl2agent_service,
        "validate_agent_generation_complete_impl",
        new=AsyncMock(),
    )

    result_json, state_wrapper = (
        await save_agent_draft_fields(
            42,
            {
                "greeting_message": "Hello",
                "example_questions": ["What should I research?"],
            },
        )
    ).split("\n", 1)

    assert json.loads(result_json)["updated_fields"] == [
        "greeting_message",
        "example_questions",
    ]
    assert json.loads(
        state_wrapper.removeprefix("<nl2a_state>").removesuffix(
            "</nl2a_state>"
        )
    ) == {
        "event": "agent_generation_completed",
        "agent_id": 42,
    }
    save_impl.assert_called_once()
    validate_complete.assert_awaited_once_with(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fields", "updated_fields"),
    [
        (
            {
                "constraint_prompt": "Use reliable sources.",
                "greeting_message": "Hello",
                "example_questions": ["What should I research?"],
            },
            [
                "constraint_prompt",
                "greeting_message",
                "example_questions",
            ],
        ),
        (
            {"example_questions": ["What should I research?"]},
            ["example_questions"],
        ),
        ({"duty_prompt": "Research the requested topic."}, ["duty_prompt"]),
        (
            {"constraint_prompt": "Use reliable sources."},
            ["constraint_prompt"],
        ),
        (
            {"few_shots_prompt": "Question: Example\nAnswer: Example"},
            ["few_shots_prompt"],
        ),
    ],
)
async def test_completion_validation_uses_persisted_state_for_prompt_saves(
    mocker,
    fields,
    updated_fields,
):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        return_value={
            "status": "success",
            "agent_id": 42,
            "created": False,
            "updated_fields": updated_fields,
        },
    )
    validate_complete = mocker.patch.object(
        nl2agent_service,
        "validate_agent_generation_complete_impl",
        new=AsyncMock(),
    )

    result_json, state_wrapper = (
        await save_agent_draft_fields(42, fields)
    ).split("\n", 1)

    assert json.loads(result_json)["updated_fields"] == updated_fields
    assert json.loads(
        state_wrapper.removeprefix("<nl2a_state>").removesuffix(
            "</nl2a_state>"
        )
    ) == {
        "event": "agent_generation_completed",
        "agent_id": 42,
    }
    validate_complete.assert_awaited_once_with(
        agent_id=42,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fields", "updated_fields"),
    [
        ({"greeting_message": "Hello"}, ["greeting_message"]),
        ({"duty_prompt": "Research the requested topic."}, ["duty_prompt"]),
    ],
)
async def test_partial_prompt_save_remains_saved_when_database_is_incomplete(
    mocker, fields, updated_fields
):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        return_value={
            "status": "success",
            "agent_id": 42,
            "created": False,
            "updated_fields": updated_fields,
        },
    )
    mocker.patch.object(
        nl2agent_service,
        "validate_agent_generation_complete_impl",
        new=AsyncMock(
            side_effect=nl2agent_service.Nl2AgentCompletionError(
                "prompt_fields_incomplete",
                ["example_questions"],
            )
        ),
    )

    result_json, state_wrapper = (await save_agent_draft_fields(42, fields)).split(
        "\n", 1
    )

    assert json.loads(result_json)["updated_fields"] == updated_fields
    assert json.loads(
        state_wrapper.removeprefix("<nl2a_state>").removesuffix(
            "</nl2a_state>"
        )
    ) == {
        "event": "agent_draft_fields_saved",
        "agent_id": 42,
        "updated_fields": updated_fields,
    }


@pytest.mark.asyncio
async def test_final_prompt_batch_emits_failure_when_database_is_incomplete(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        return_value={
            "status": "success",
            "agent_id": 42,
            "created": False,
            "updated_fields": ["greeting_message", "example_questions"],
        },
    )
    mocker.patch.object(
        nl2agent_service,
        "validate_agent_generation_complete_impl",
        new=AsyncMock(
            side_effect=nl2agent_service.Nl2AgentCompletionError(
                "prompt_fields_incomplete",
                ["few_shots_prompt"],
            )
        ),
    )

    result_json, state_wrapper = (
        await save_agent_draft_fields(
            42,
            {
                "greeting_message": "Hello",
                "example_questions": ["What should I research?"],
            },
        )
    ).split("\n", 1)

    assert json.loads(result_json) == {
        "status": "error",
        "agent_id": 42,
        "created": False,
        "updated_fields": [],
        "code": "prompt_fields_incomplete",
        "retryable": True,
    }
    assert json.loads(
        state_wrapper.removeprefix("<nl2a_state>").removesuffix(
            "</nl2a_state>"
        )
    ) == {
        "event": "prompt_generation_failed",
        "agent_id": 42,
        "failed_fields": ["few_shots_prompt"],
    }


@pytest.mark.asyncio
async def test_save_agent_draft_fields_returns_stable_non_sensitive_errors(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "save_agent_draft_fields_impl",
        side_effect=nl2agent_service.Nl2AgentDraftSaveError("agent_read_only"),
    )

    error_result = json.loads(
        await save_agent_draft_fields(1042, {"description": "Updated"})
    )
    assert error_result == {
        "status": "error",
        "agent_id": 1042,
        "created": False,
        "updated_fields": [],
        "code": "agent_read_only",
        "retryable": False,
    }
    assert "database" not in json.dumps(error_result).lower()

    invalid_result = json.loads(
        await save_agent_draft_fields(1042, {"description": None})
    )
    assert invalid_result["code"] == "invalid_agent_fields"
    assert invalid_result["retryable"] is False

    nl2agent_mcp_tools_module.get_current_user_id.side_effect = PermissionError(
        "private authorization details"
    )
    unauthorized_result = json.loads(
        await save_agent_draft_fields(1042, {"description": "Updated"})
    )
    assert unauthorized_result["code"] == "unauthorized"
    assert "private authorization details" not in json.dumps(unauthorized_result)

    nl2agent_mcp_tools_module.get_current_user_id.side_effect = RuntimeError(
        "private database details"
    )
    failed_result = json.loads(
        await save_agent_draft_fields(1042, {"description": "Updated"})
    )
    assert failed_result["code"] == "draft_save_failed"
    assert failed_result["retryable"] is True
    assert "private database details" not in json.dumps(failed_result)


def test_requirement_clarification_rejects_invalid_question_shapes():
    with pytest.raises(ValidationError, match="cannot have options"):
        RequirementClarificationQuestion(
            question_id="details",
            question_type="text",
            title="Add details",
            options=[{"option_id": "unexpected", "label": "Unexpected"}],
        )

    with pytest.raises(ValidationError, match="require options"):
        RequirementClarificationQuestion(
            question_id="output",
            question_type="single_choice",
            title="Choose an output",
        )


@pytest.mark.asyncio
async def test_requirement_clarification_wrapper_requires_agent_id():
    with pytest.raises(TypeError, match="agent_id"):
        await nl2a_wrapper(
            subtype="requirement_clarification",
            questions=[],
        )


@pytest.mark.asyncio
async def test_local_mcp_service_preserves_existing_demo_tool(capsys):
    registered_tools = await local_mcp_service.get_tools()

    result = await registered_tools["test_tool_name"].fn("sample", 2)

    assert result == "success"
    assert capsys.readouterr().out.splitlines() == [
        "tool is called successfully",
        "sample 2",
    ]


@pytest.mark.asyncio
async def test_mcp_search_empty_result_returns_business_payload(mocker):
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_http_request",
        return_value=SimpleNamespace(headers={"Authorization": "Bearer tenant-token"}),
    )
    mocker.patch.object(
        nl2agent_mcp_tools_module,
        "get_current_user_id",
        return_value=("user-a", "tenant-a"),
    )
    mocker.patch.object(
        nl2agent_service,
        "search_installed_mcp_tools_by_query",
        return_value=[],
    )

    result = await search_installed_mcp_tools(["weather"])

    assert result == {
        "subtype": "local_mcp_recommendation",
        "status": "success",
        "recommendation_count": 0,
        "recommendations": [],
    }


@pytest.mark.asyncio
async def test_public_mcp_scanner_skips_internal_tools(mocker):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.list_tools.return_value = [
        Tool(
            name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
            description="Internal search",
            inputSchema={"type": "object", "properties": {}},
            _meta={"nexent_internal": True},
        ),
        Tool(
            name=NL2A_WRAPPER_NAME,
            description="Internal wrapper",
            inputSchema={"type": "object", "properties": {}},
            _meta={"nexent_internal": True},
        ),
        Tool(
            name="public_weather",
            description="Public weather tool",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]
    client_class = mocker.patch.object(
        tool_configuration_service,
        "Client",
        return_value=client,
    )
    transport = mocker.patch.object(
        tool_configuration_service,
        "_create_mcp_transport",
        return_value=object(),
    )

    result = await get_tool_from_remote_mcp_server(
        "outer-apis",
        "http://mcp.example/sse",
    )

    transport.assert_called_once_with("http://mcp.example/sse", None, None)
    client_class.assert_called_once()
    assert [tool.name for tool in result] == ["public_weather"]
