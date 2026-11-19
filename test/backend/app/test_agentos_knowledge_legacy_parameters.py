# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Export SDK-compatible knowledge parameters without constructing legacy clients."""

import pytest
from contracts.agentos import KnowledgeSearchBinding, ToolBinding
from management.services.agent.preparation import knowledge_search
from nexent.core.agents.contracts.config import ToolConfig
from runtime.agentos import prepared_knowledge
from runtime.knowledge_base.tool import KnowledgeBaseSearchTool

from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.parametrize("raw,expected", [
    (None, 3), ("7", 7), (2.9, 2), (True, 1), (False, 3), ("0", 1), (0, 3), (200, 100), (-4, 1),
])
@pytest.mark.asyncio
async def test_top_k_keeps_the_legacy_sdk_value_across_json_and_runtime(mocker, raw, expected):
    tool = ToolConfig(
        name="knowledge_base_search", class_name="KnowledgeBaseSearchTool", source="local",
        params={"index_names": [], "top_k": raw},
    )
    mocker.patch.object(knowledge_search, "read_knowledge_search_records", return_value=[])
    mocker.patch.object(knowledge_search, "resolve_knowledge_base_permissions", return_value={})
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    model = AsyncMock()
    mocker.patch.object(knowledge_search, "AgentOSClient", return_value=SimpleNamespace(get_model=model))
    async def blocking(name, method, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return method(*args, **kwargs)
    mocker.patch.object(knowledge_search, "run_blocking", side_effect=blocking)
    assert await knowledge_search.prepare_knowledge_search(tool, "actor", "tenant", None)
    encoded = ToolBinding(
        tool_id=tool.name, version="2", parameters=tool.metadata["prepared_knowledge_search"],
    ).model_dump_json()
    binding = ToolBinding.model_validate_json(encoded)
    assert KnowledgeSearchBinding.model_validate(binding.parameters).top_k == expected
    materialized = prepared_knowledge.materialize_knowledge_search([binding], ServicePrincipal("actor", "tenant"))
    original = KnowledgeBaseSearchTool(top_k=raw, index_names=[])
    restored = KnowledgeBaseSearchTool(**materialized[tool.name].params)
    assert restored.top_k == original.top_k == expected
    assert tool.params["top_k"] is raw
    model.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, "7", 2.9, True, False, "0"])
async def test_portable_compiler_does_not_initialize_legacy_clients_for_valid_sdk_values(mocker, raw):
    from management.services.agent.preparation import tools

    definition = {
        "name": "knowledge_base_search", "class_name": "KnowledgeBaseSearchTool", "source": "local",
        "usage": "knowledge", "description": "Search", "description_zh": None, "inputs": None,
        "output_type": "string", "instance_params": {},
        "params": [{"name": "index_names", "default": []}, {"name": "top_k", "default": 3}],
    }
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[definition])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "root"})
    vector = mocker.patch.object(tools, "get_vector_db_core", side_effect=AssertionError("legacy vector client"))
    embedding = mocker.patch.object(tools, "get_embedding_model_by_index_name", side_effect=AssertionError("legacy model"))
    mocker.patch.object(knowledge_search, "read_knowledge_search_records", return_value=[])
    mocker.patch.object(knowledge_search, "resolve_knowledge_base_permissions", return_value={})
    compiled = await tools.create_tool_config_list(
        7, "tenant", "actor", portable_evaluation=True,
        tool_params={"agents": {"root": {"tools": {"knowledge_base_search": {"top_k": raw}}}}},
    )
    result, = compiled
    expected = KnowledgeBaseSearchTool(top_k=raw, index_names=[]).top_k
    assert result.metadata["prepared_knowledge_search"]["top_k"] == expected
    vector.assert_not_called()
    embedding.assert_not_called()


@pytest.mark.parametrize("raw", ["invalid", [2], {"value": 2}])
@pytest.mark.asyncio
async def test_invalid_sdk_values_are_not_silently_replaced_or_authorized(mocker, raw):
    tool = ToolConfig(
        name="knowledge_base_search", class_name="KnowledgeBaseSearchTool", source="local",
        params={"index_names": [], "top_k": raw},
    )
    catalog = mocker.patch.object(knowledge_search, "read_knowledge_search_records")
    assert await knowledge_search.prepare_knowledge_search(tool, "actor", "tenant", None) is False
    with pytest.raises((ValueError, TypeError)):
        KnowledgeBaseSearchTool(top_k=raw, index_names=[])
    catalog.assert_not_called()
    assert tool.metadata is None and tool.params["top_k"] == raw
