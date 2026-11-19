# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SEED-TEXT-04 keeps seed writes in the awaited installation flow."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agent import KnowledgeBaseSeedDoc
from management.db.identity import group
from management.db.knowledge_base import repository
from management.services.knowledge_base import common, creation, seed_documents
from management.services.knowledge_base.service import ElasticSearchService
from management.services.model import resolver
from management.services.repository.agent import official


@pytest.mark.parametrize("error", [RuntimeError("write failed"), asyncio.CancelledError()])
async def test_install_stops_after_text_write_failure_without_starting_binary_or_next_kb(mocker, error):
    doc = KnowledgeBaseSeedDoc(file_name="seed.md", content="text", file_path="unused")
    kb = SimpleNamespace(logical_index_name="logical", display_name="KB", documents=[doc])
    bundle = SimpleNamespace(knowledge_bases=[kb, kb])
    mocker.patch.object(group, "query_groups_by_tenant", return_value={"groups": []})
    mocker.patch.object(repository, "get_knowledge_record", return_value=None)
    mocker.patch.object(common, "get_vector_db_core")
    mocker.patch.object(resolver, "get_embedding_model_by_id", return_value=(SimpleNamespace(model="model"), 2))
    create = mocker.patch.object(creation, "create_knowledge_base", new=AsyncMock(return_value={"id": "actual"}))
    mocker.patch.object(seed_documents, "get_seed_model_name", new=AsyncMock(return_value="model"))
    assert not hasattr(ElasticSearchService, "index_documents")
    text = mocker.patch.object(seed_documents, "index_seed_texts", new=AsyncMock(side_effect=error))
    binary = mocker.patch.object(official, "_index_binary_docs", new_callable=AsyncMock)
    with pytest.raises(type(error)) as caught:
        await official._create_knowledge_bases(bundle, "tenant-a", "operator", 2, "credential-not-forwarded")
    assert caught.value is error
    assert create.call_count == 1 and text.await_count == 1
    assert text.await_args.args[0] == "actual" and text.await_args.args[1] == [doc]
    assert text.await_args.args[2].user_id == "operator" and text.await_args.args[2].tenant_id == "tenant-a"
    assert text.await_args.kwargs == {"embedding_model_name": "model"}
    binary.assert_not_called()
