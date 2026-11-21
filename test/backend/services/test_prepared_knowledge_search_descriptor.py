# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Freeze only tenant-authorized knowledge indexes and applicable model revisions."""

import pytest

from contracts.agentos import KnowledgeSearchBinding
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
    mocker.patch.object(service, "get_model_by_model_id", return_value={"model_id": 11, "model_type": "embedding"})
    mocker.patch.object(service, "model_record_revision", side_effect=lambda record: f"revision-{record['model_id']}")
    mocker.patch.object(service, "find_named_rerank_record", side_effect=RuntimeError("catalog unavailable"))
    mocker.patch.object(service.tenant_config_manager, "get_model_config", return_value={"model_type": "chat"})
    return tool, row


@pytest.mark.parametrize("mode", ["duplicate", "invalid", "unknown-parameter", "wrong-source"])
def test_invalid_search_descriptors_cannot_bind_runtime_tools(search, mode):
    tool, row = search
    if mode == "duplicate":
        service.read_knowledge_search_records.return_value = [row, row]
    elif mode == "invalid":
        tool.params["top_k"] = float("inf")
    elif mode == "unknown-parameter":
        tool.params["extra"] = True
    else:
        tool.source = "mcp"
    assert service.prepare_knowledge_search(tool, "actor", "tenant", None) is False
    assert tool.metadata is None
    service.get_model_by_model_id.assert_not_called()


def test_unusable_embedding_and_reranker_never_bind_vector_models(search):
    tool, row = search
    service.get_model_by_model_id.return_value = {"model_id": 11, "model_type": "llm"}
    with pytest.raises(ValidationError, match="No embedding model found"):
        service.prepare_knowledge_search(tool, "actor", "tenant", None)
    assert tool.metadata is None

    service.get_model_by_model_id.return_value = {"model_id": 11, "model_type": "embedding"}
    assert service.prepare_knowledge_search(tool, "actor", "tenant", None) is True
    result = KnowledgeSearchBinding.model_validate(tool.metadata["prepared_knowledge_search"])
    assert [item.index_name for item in result.allowed] == ["records"]
    assert result.embedding.model_id == 11
    assert result.reranker is None and result.default_reranker is None
    service.get_model_by_model_id.assert_called_with(row["embedding_model_id"], "tenant")
