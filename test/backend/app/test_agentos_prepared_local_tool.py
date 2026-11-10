# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.agentos import ToolBinding
from contracts.constants import environment
from infrastructure.agentos_identity import ServicePrincipal
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent


@pytest.fixture
def stored_tool(mocker):
    mocker.patch.object(environment, "JWT_SECRET", "synthetic-local-tool-secret")
    return {
        "tool_instance_id": 24, "tool_id": 10, "name": "dify_search", "class_name": "DifySearchTool",
        "source": "local", "description": "Search", "usage": None, "inputs": None, "output_type": "string",
        "params": [{"name": name, "default": value} for name, value in {
            "server_url": "https://private-dify.invalid/v1", "api_key": "local-only-dify-key",
            "dataset_ids": '["dataset-a"]', "top_k": 4, "rerank": True, "rerank_model_name": "Reranker",
        }.items()],
        "instance_params": {"top_k": 2, "dataset_ids": None},
    }


@pytest.mark.asyncio
async def test_local_tool_compiles_and_rebinds_without_sending_connection_fields(mocker, stored_tool):
    from management.services.agent.preparation import local_tool, tools
    from runtime.agentos import prepared_local_tool

    params = [{**item, "default": 2} if item["name"] == "top_k" else item for item in stored_tool["params"]]
    mocker.patch.object(tools, "discover_langchain_tools", return_value=[])
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[
        {**stored_tool, "params": params, "description_zh": "检索"},
    ])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={})
    legacy = mocker.patch.object(tools, "get_rerank_model")
    tool, = await tools.create_tool_config_list(7, "tenant-a", "user-a", version_no=3, portable_evaluation=True)
    legacy.assert_not_called()

    rerank = mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    exported = local_tool.export_local_tool(tool, [stored_tool], 7, 3, "tenant-a", "zh")
    rerank.assert_called_once_with("tenant-a", "Reranker")
    encoded = exported.model_dump_json()
    for secret in ("https://private-dify.invalid/v1", "local-only-dify-key", "dataset-a"):
        assert secret not in encoded
    lookup = mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[stored_tool])
    hydrate_rerank = mocker.patch.object(prepared_local_tool, "_reranker")
    resource = SimpleNamespace(agent_id=7, version_no=3, tools=[ToolBinding.model_validate_json(encoded)])
    rebound = prepared_local_tool.materialize_local_tools(resource, ServicePrincipal("user-a", "tenant-a"), "zh")[tool.name]
    lookup.assert_called_once_with(7, 3, "tenant-a", ["dify_search"])
    assert rebound.description_zh == "检索"
    assert rebound.params == tool.params
    instance = NexentAgent.create_local_tool(SimpleNamespace(observer=None), rebound)
    assert instance.dataset_ids == ["dataset-a"]
    assert instance.top_k == 2
    assert instance.rerank_model is hydrate_rerank.return_value


@pytest.mark.parametrize(("change", "status"), [("revoked", 404), ("changed", 409)])
def test_local_tool_refuses_removed_or_changed_binding(mocker, stored_tool, change, status):
    from management.services.agent.preparation import local_tool
    from runtime.agentos import prepared_local_tool

    tool = ToolConfig(
        class_name="DifySearchTool", name="dify_search", description="Search", output_type="string",
        source="local", params={item["name"]: item["default"] for item in stored_tool["params"]} | {"top_k": 2},
    )
    mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    binding = local_tool.export_local_tool(tool, [stored_tool], 7, 3, "tenant-a", "zh")
    rows = [] if change == "revoked" else [{**stored_tool, "instance_params": {"top_k": 9}}]
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=rows)
    hydrate_rerank = mocker.patch.object(prepared_local_tool, "_reranker")

    with pytest.raises(HTTPException) as error:
        prepared_local_tool.materialize_local_tools(
            SimpleNamespace(agent_id=7, version_no=3, tools=[binding]),
            ServicePrincipal("user-a", "tenant-a"), "zh",
        )

    assert error.value.status_code == status
    hydrate_rerank.assert_not_called()


def test_local_tool_export_rejects_request_overrides(stored_tool):
    from management.services.agent.preparation import local_tool

    params = {item["name"]: item["default"] for item in stored_tool["params"]}
    tool = ToolConfig(
        class_name="DifySearchTool", name="dify_search", description="Search", output_type="string",
        source="local", params=params | {"top_k": 2, "api_key": "request-only-key"},
    )
    with pytest.raises(ValueError):
        local_tool.export_local_tool(tool, [stored_tool], 7, 3, "tenant-a", "zh")


def test_local_deepseek_reconstruction_uses_runtime_language(mocker, stored_tool):
    from infrastructure.local_tool_execution import build_local_tool, local_tool_revision
    from management.services.agent.preparation import local_tool
    from runtime.agentos import prepared_local_tool

    row = {
        **stored_tool, "name": "deepseek_search", "class_name": "DeepSeekSearchTool",
        "params": [
            {"name": "api_key", "default": "fixture-only-key"},
            {"name": "localization", "default": "en"},
            {"name": "max_content_chars", "default": 200},
            {"name": "language", "default": "en"},
        ],
    }
    tool = build_local_tool(row, "zh", None, None)
    assert tool.params == {"api_key": "fixture-only-key", "language": "zh"}
    binding = local_tool.export_local_tool(tool, [row], 7, 3, "tenant-a", "zh")
    assert binding.parameters["revision"] == local_tool_revision("tenant-a", 7, 3, row, tool)
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[row])
    with pytest.raises(HTTPException) as error:
        prepared_local_tool.materialize_local_tools(
            SimpleNamespace(agent_id=7, version_no=3, tools=[binding]), ServicePrincipal("user-a", "tenant-a"), "en",
        )
    assert error.value.status_code == 409


def test_local_tool_credential_override_is_rejected_before_repository_access(mocker):
    from runtime.agentos import prepared_local_tool

    lookup = mocker.patch.object(prepared_local_tool, "read_bound_local_tools")
    binding = ToolBinding(tool_id="dify_search", version="1", credential_ref="injected")
    with pytest.raises(ValueError, match="Unsupported local SDK tool binding"):
        prepared_local_tool.materialize_local_tools(
            SimpleNamespace(agent_id=7, version_no=3, tools=[binding]), ServicePrincipal("user-a", "tenant-a"), "zh",
        )
    lookup.assert_not_called()
