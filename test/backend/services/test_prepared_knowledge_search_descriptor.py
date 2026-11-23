# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Freeze only tenant-authorized knowledge indexes and applicable model revisions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agentos import KnowledgeSearchBinding, ModelMetadata
from contracts.errors.exceptions import ValidationError
from management.services.agent.preparation import knowledge_search as service
from nexent.core.agents.contracts.config import ToolConfig


@pytest.fixture
def search(mocker):
    tool = ToolConfig(
        name="search", class_name="KnowledgeBaseSearchTool", source="local",
        description="Search resources", params={"index_names": ["records"], "rerank": True, "rerank_model_name": "rank"},
    )
    row = {"index_name": "records", "knowledge_id": 41, "tenant_id": "tenant",
           "knowledge_name": "Records", "embedding_model_id": 11}
    mocker.patch.object(service, "read_knowledge_search_records", return_value=[row])
    mocker.patch.object(service, "knowledge_search_revision", return_value="a" * 64)
    mocker.patch.object(service, "resolve_knowledge_base_permissions", return_value={"records": "read"})
    async def in_process(_action, fn, *args, lane, owner, **kwargs):
        return fn(*args, **kwargs)

    mocker.patch.object(service, "run_blocking", side_effect=in_process)
    client = SimpleNamespace(get_model=AsyncMock(), list_models=AsyncMock(return_value=SimpleNamespace(models=[], next_cursor=None)))
    mocker.patch.object(service, "AgentOSClient", return_value=client)
    mocker.patch.object(service.tenant_config_manager, "get_app_config", return_value=12)
    return tool, row, client


@pytest.mark.parametrize("mode", ["duplicate", "invalid", "unknown-parameter", "user-native-option", "wrong-source"])
async def test_invalid_search_descriptors_cannot_bind_runtime_tools(search, mode):
    tool, row, client = search
    if mode == "duplicate":
        service.read_knowledge_search_records.return_value = [row, row]
    elif mode == "invalid":
        tool.params["top_k"] = float("inf")
    elif mode == "unknown-parameter":
        tool.params["extra"] = True
    elif mode == "user-native-option":
        tool.params["native_documents"] = True
    else:
        tool.source = "mcp"
    assert await service.prepare_knowledge_search(tool, "actor", "tenant", None) is False
    assert tool.metadata is None
    client.get_model.assert_not_awaited()


@pytest.mark.parametrize("native", [False, True])
async def test_unusable_embedding_and_reranker_never_bind_vector_models(search, monkeypatch, native):
    tool, row, client = search
    monkeypatch.setattr(service.environment, "KNOWLEDGE_RUNTIME_HYBRID_ENABLED", native)
    client.get_model.return_value = ModelMetadata(model_id=11, revision="v11", model_type="llm", display_name=None)
    with pytest.raises(ValidationError, match="Invalid embedding model"):
        await service.prepare_knowledge_search(tool, "actor", "tenant", None)
    assert tool.metadata is None

    client.get_model.side_effect = [
        ModelMetadata(model_id=11, revision="v11", model_type="embedding", display_name=None),
        ModelMetadata(model_id=12, revision="v12", model_type="llm", display_name=None),
    ]
    assert await service.prepare_knowledge_search(tool, "actor", "tenant", None) is True
    prepared = tool.metadata["prepared_knowledge_search"]
    result = KnowledgeSearchBinding.model_validate(prepared)
    assert [item.index_name for item in result.allowed] == ["records"]
    assert result.embedding_models["records"].model_id == 11
    assert result.reranker is None and result.default_reranker is None
    assert result.native_documents is native and ("native_documents" in prepared) is native
    client.get_model.assert_any_await(row["embedding_model_id"], "actor", "tenant")
