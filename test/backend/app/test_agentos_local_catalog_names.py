# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep SDK class execution when a local tool has a different catalog name."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.agentos import PreparedEvaluationRun
from infrastructure.agent_model_config import create_model_config_from_record
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.local_tool_execution import catalog_tool_parameters
from management.services.agent.preparation import evaluation_snapshot, local_tool
from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from runtime.agentos import prepared_local_tool
from test.backend.app.test_agentos_prepared_evaluation import model_record
from test.backend.app.test_agentos_prepared_local_tool import stored_tool


@pytest.mark.parametrize("name", ["tenant_search", "mcp", "analyze_image"])
def test_local_catalog_name_crosses_export_and_keeps_actual_sdk_behavior(mocker, stored_tool, name):
    stored_tool["name"] = name
    original = ToolConfig(
        name=name, class_name="DifySearchTool", source="local", description=stored_tool["description"],
        output_type=stored_tool["output_type"], params=catalog_tool_parameters(stored_tool),
    )
    legacy = NexentAgent.create_local_tool(SimpleNamespace(observer=None), original)
    record = model_record(model_id=11)
    model = create_model_config_from_record(record)
    root = AgentConfig(agent_id=7, version_no=3, name="root", description="", model_name=model.cite_name, tools=[original])
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[record])
    lookup = mocker.patch.object(evaluation_snapshot, "read_bound_local_tools", return_value=[stored_tool])
    mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    snapshot = evaluation_snapshot.export_snapshot(root, [model], "hello", None,
                                                  tenant_id="tenant-a", conversation_id=0, language="zh")
    assert snapshot is not None
    lookup.assert_called_once_with(7, 3, "tenant-a", [name])
    encoded = snapshot.model_dump_json()
    assert "local-only-dify-key" not in encoded and "dataset-a" not in encoded
    binding, = PreparedEvaluationRun.model_validate_json(encoded).resource.tools
    assert binding.tool_id == "sdk_local:" + name
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[stored_tool])
    mocker.patch.object(prepared_local_tool, "_reranker", return_value=None)
    restored = prepared_local_tool.materialize_local_tools(
        SimpleNamespace(agent_id=7, version_no=3, tools=[binding]), ServicePrincipal("user-a", "tenant-a"), "zh",
    )[binding.tool_id]
    actual = NexentAgent.create_local_tool(SimpleNamespace(observer=None), restored)
    assert restored.name == original.name and restored.params == original.params
    assert actual.name == legacy.name == "dify_search"
    assert (actual.dataset_ids, actual.top_k, actual.api_key) == (legacy.dataset_ids, legacy.top_k, legacy.api_key)


@pytest.mark.parametrize("changed", ["removed", "class", "name"])
def test_noncanonical_local_binding_still_pins_catalog_revision_and_scope(mocker, stored_tool, changed):
    from infrastructure.local_tool_execution import build_local_tool

    stored_tool["name"] = "tenant_search"
    original = build_local_tool(stored_tool, "zh", None, None)
    mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    binding = local_tool.export_local_tool(original, [stored_tool], 7, 3, "tenant-a", "zh")
    rows = [] if changed == "removed" else [{**stored_tool, **(
        {"class_name": "TerminalTool"} if changed == "class" else {"name": "different"}
    )}]
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=rows)
    with pytest.raises(HTTPException) as rejected:
        prepared_local_tool.materialize_local_tools(SimpleNamespace(agent_id=7, version_no=3, tools=[binding]),
                                                    ServicePrincipal("user-a", "tenant-a"), "zh")
    assert rejected.value.status_code in {404, 409}


def test_catalog_alias_retains_deepseek_language_and_override_limits(stored_tool):
    from contracts.agentos import LocalSearchOverrides
    from infrastructure.local_tool_execution import (
        apply_local_parameter_overrides, apply_local_search_overrides, build_local_tool,
    )

    row = {**stored_tool, "name": "tenant_web", "class_name": "DeepSeekSearchTool", "params": [
        {"name": "language", "default": "en"},
        {"name": "localization", "default": "en"},
        {"name": "max_content_chars", "default": 200},
    ], "instance_params": {}}
    tool = build_local_tool(row, "zh", None, None)
    assert tool.params == {"language": "zh"}
    overridden = apply_local_parameter_overrides(tool, {
        "language": "en", "localization": "en", "max_content_chars": 100, "max_results": 5,
    })
    assert overridden.params == {"language": "zh", "max_results": 5}
    with pytest.raises(ValueError, match="up to 50"):
        apply_local_search_overrides(tool, LocalSearchOverrides(max_results=51))


def test_empty_catalog_binding_is_rejected_before_repository_access(mocker):
    from contracts.agentos import ToolBinding

    lookup = mocker.patch.object(prepared_local_tool, "read_bound_local_tools")
    with pytest.raises(ValueError, match="catalog name"):
        prepared_local_tool.materialize_local_tools(
            SimpleNamespace(tools=[ToolBinding(tool_id="sdk_local:", version="1", parameters={})]),
            ServicePrincipal("user-a", "tenant-a"), "zh",
        )
    lookup.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["tenant_search", "mcp", "analyze_image"])
async def test_management_compiles_alias_search_tuning_without_credential_scope(mocker, stored_tool, name):
    from infrastructure.local_tool_execution import LOCAL_SEARCH_TUNING_METADATA
    from management.services.agent.preparation import tools

    row = {**stored_tool, "name": name}
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[row])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "root"})
    compiled, = await tools.create_tool_config_list(
        7, "tenant-a", "user-a", version_no=3, language="zh", portable_evaluation=True,
        tool_params={"agents": {"root": {"tools": {name: {"top_k": 7}}}}},
    )
    assert compiled.name == name and compiled.class_name == "DifySearchTool"
    assert compiled.params["top_k"] == 7
    assert compiled.metadata == {LOCAL_SEARCH_TUNING_METADATA: {"top_k": 7}}
    mocker.patch.object(local_tool, "_rerank_bindings", return_value=(None, None))
    binding = local_tool.export_local_tool(compiled, [row], 7, 3, "tenant-a", "zh")
    assert binding.tool_id == "sdk_local:" + name
    assert binding.parameters["search_overrides"] == {"top_k": 7}
    assert binding.credential_ref is None
