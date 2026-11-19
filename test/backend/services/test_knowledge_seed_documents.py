# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SEED-TEXT-01/02/03 preserve official text seed write behavior."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from contracts.agent import KnowledgeBaseSeedDoc
from management.services.knowledge_base import seed_documents

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def writer(mocker):
    mocker.patch.object(seed_documents.time, "time", return_value=1234)
    create = mocker.patch.object(seed_documents, "create_manual_chunk", new_callable=AsyncMock)
    return create, ServicePrincipal("operator", "tenant-a")


async def test_seed_text_preserves_source_defaults_key_and_actual_identity(writer):
    create, actor = writer
    docs = [KnowledgeBaseSeedDoc(file_name="a.md", content="first"), KnowledgeBaseSeedDoc(file_name="b.txt", content="second")]
    count = await seed_documents.index_seed_texts("kb", docs, actor, embedding_model_name="embedding-v1")
    assert count == 2 and create.await_count == 2
    for call, doc in zip(create.await_args_list, docs, strict=True):
        index, payload, principal = call.args
        assert index == "kb" and principal == actor
        assert call.kwargs == {"require_embedding": True}
        assert payload.content == doc.content and payload.chunk_id == f"1234_{hash(doc.content)}"[:20]
        assert payload.title == payload.filename == payload.path_or_url == doc.file_name
        assert payload.metadata == {
            "source_type": "local", "language": "null", "author": "null", "date": "1970-01-01",
            "create_time": datetime.fromtimestamp(1234, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "process_source": "Unstructured", "file_size": 0, "languages": [], "embedding_model_name": "embedding-v1",
        }


async def test_empty_seeds_are_not_written_and_same_second_duplicates_keep_the_key(writer):
    create, actor = writer
    docs = [KnowledgeBaseSeedDoc(file_name="empty"), KnowledgeBaseSeedDoc(file_name="empty", content=""),
            KnowledgeBaseSeedDoc(file_name="a", content="same"), KnowledgeBaseSeedDoc(file_name="b", content="same")]
    assert await seed_documents.index_seed_texts("kb", docs, actor, embedding_model_name="model") == 2
    assert create.await_args_list[0].args[1].chunk_id == create.await_args_list[1].args[1].chunk_id


@pytest.mark.parametrize("error", [RuntimeError("failed"), asyncio.CancelledError()])
async def test_failed_or_cancelled_seed_stops_without_replay_or_success(writer, error):
    create, actor = writer
    create.side_effect = [None, error]
    docs = [KnowledgeBaseSeedDoc(file_name=str(i), content=f"content {i}") for i in range(3)]
    with pytest.raises(type(error)) as caught:
        await seed_documents.index_seed_texts("kb", docs, actor, embedding_model_name="model")
    assert caught.value is error and create.await_count == 2
