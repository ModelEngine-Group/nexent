# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Each prepared collection must retain its own versioned embedding model."""

import pytest
from contracts.agentos import KnowledgeSearchBinding, ToolBinding
from management.services.agent.preparation import knowledge_search
from nexent.core.agents.agent_model import ToolConfig
from runtime.agentos import prepared_knowledge

from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.asyncio
async def test_preparation_uses_one_deadline_and_does_not_publish_after_timeout(mocker, caplog):
    import asyncio

    from contracts.errors.exceptions import RuntimeServiceTimeoutError

    mocker.patch.object(knowledge_search, "PREPARATION_SECONDS", 0.02)
    closed = []
    contexts = []

    async def blocked(*args, **kwargs):
        contexts.append(kwargs["context"])
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    worker = mocker.patch.object(knowledge_search, "run_blocking", side_effect=blocked)
    client = mocker.patch.object(knowledge_search, "AgentOSClient")
    tool = ToolConfig(class_name="KnowledgeBaseSearchTool", name="knowledge_base_search", source="local",
                      params={"index_names": ["kb-1"]})
    with pytest.raises(RuntimeServiceTimeoutError):
        await knowledge_search.prepare_knowledge_search(tool, "private-user", "private-tenant", None)
    assert worker.await_count == 1 and closed == [True] and len(contexts) == 1
    client.assert_not_called()
    assert not (tool.metadata or {}).get("prepared_knowledge_search")
    records = [record for record in caplog.records if record.name == knowledge_search.__name__]
    assert len(records) == 1 and records[0].levelname == "WARNING"
    assert "phase=resources" in records[0].message and "private-" not in records[0].message


@pytest.mark.asyncio
async def test_snapshot_exports_every_model_and_runtime_never_builds_an_es_client(mocker):
    rows = [{"knowledge_id": i, "index_name": f"kb-{i}", "tenant_id": "tenant", "created_by": "user",
             "knowledge_name": f"KB {i}", "embedding_model_id": i + 10} for i in (1, 2)]
    models = {i: {"model_id": i, "tenant_id": "tenant", "delete_flag": "N", "model_type": "embedding",
                  "update_time": "v1", "api_key": "private-model-secret"} for i in (11, 12)}
    mocker.patch.object(knowledge_search, "read_knowledge_search_records", return_value=rows)
    mocker.patch.object(knowledge_search, "resolve_knowledge_base_permissions", return_value={"kb-1": "EDIT", "kb-2": "EDIT"})
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from contracts.agentos import ModelMetadata
    lookup = AsyncMock(side_effect=lambda i, user, tenant: ModelMetadata(
        model_id=i, model_type="embedding", display_name="Embedding", revision="v1"))
    mocker.patch.object(knowledge_search, "AgentOSClient", return_value=SimpleNamespace(get_model=lookup))
    async def blocking(name, method, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return method(*args, **kwargs)
    mocker.patch.object(knowledge_search, "run_blocking", side_effect=blocking)
    tool = ToolConfig(class_name="KnowledgeBaseSearchTool", name="knowledge_base_search", source="local",
                      params={"index_names": ["kb-1", "kb-2"]})
    assert await knowledge_search.prepare_knowledge_search(tool, "user", "tenant", None)
    binding = KnowledgeSearchBinding.model_validate(tool.metadata["prepared_knowledge_search"])
    assert {name: ref.model_id for name, ref in binding.embedding_models.items()} == {"kb-1": 11, "kb-2": 12}
    assert lookup.call_count == 2 and "private-model-secret" not in binding.model_dump_json()
    from contracts.agentos_knowledge import KnowledgeBaseGrant, KnowledgeSearchGrant

    from infrastructure.knowledge_search import knowledge_search_revision
    mocker.patch.object(prepared_knowledge, "_current_grant", return_value=KnowledgeSearchGrant(knowledge_bases=[
        KnowledgeBaseGrant(knowledge_id=row["knowledge_id"], collection=row["index_name"], embedding_model_id=row["embedding_model_id"],
                           revision=knowledge_search_revision(row)) for row in rows]))
    mocker.patch.object(prepared_knowledge, "get_model_by_model_id", side_effect=lambda i, tenant: models[i])
    client = mocker.patch("infrastructure.vdb.client.create_elasticsearch_core")
    result = prepared_knowledge.materialize_knowledge_search([ToolBinding(
        tool_id=tool.name, version="2", parameters=binding.model_dump(mode="json"))], ServicePrincipal("user", "tenant"))[tool.name]
    assert callable(result.metadata["knowledge_searcher"])
    assert not {"vdb_core", "embedding_model", "rerank_model", "document_paths"} & result.metadata.keys()
    client.assert_not_called()


def test_old_knowledge_wire_version_is_rejected_without_storage_access(mocker):
    lookup = mocker.patch.object(prepared_knowledge, "_current_grant")
    with pytest.raises(ValueError):
        prepared_knowledge.materialize_knowledge_search([ToolBinding(tool_id="knowledge_base_search", version="1")],
                                                       ServicePrincipal("user", "tenant"))
    lookup.assert_not_called()
