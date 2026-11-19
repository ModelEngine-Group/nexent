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
    create = mocker.patch.object(seed_documents, "append_documents", new_callable=AsyncMock)
    create.side_effect = lambda index, documents, actor: len(documents)
    return create, ServicePrincipal("operator", "tenant-a")


async def test_seed_text_preserves_source_defaults_key_and_actual_identity(writer):
    create, actor = writer
    docs = [KnowledgeBaseSeedDoc(file_name="a.md", content="first"), KnowledgeBaseSeedDoc(file_name="b.txt", content="second")]
    count = await seed_documents.index_seed_texts("kb", docs, actor, embedding_model_name="embedding-v1")
    assert count == 2 and create.await_count == 1
    call = create.await_args
    assert call.args[0] == "kb" and call.args[2] == actor
    for payload, doc in zip(call.args[1], docs, strict=True):
        assert payload.content == doc.content
        assert payload.metadata == {
            "title": doc.file_name, "filename": doc.file_name, "path_or_url": doc.file_name,
            "source_type": "local", "language": "null", "author": "null", "date": "1970-01-01",
            "create_time": datetime.fromtimestamp(1234, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "process_source": "Unstructured", "file_size": 0, "languages": [], "embedding_model_name": "embedding-v1",
        }



async def test_empty_seeds_are_not_written_and_repeated_texts_are_not_collapsed(writer):
    create, actor = writer
    docs = [KnowledgeBaseSeedDoc(file_name="empty"), KnowledgeBaseSeedDoc(file_name="empty", content=""),
            KnowledgeBaseSeedDoc(file_name="a", content="same"), KnowledgeBaseSeedDoc(file_name="b", content="same")]
    assert await seed_documents.index_seed_texts("kb", docs, actor, embedding_model_name="model") == 2
    assert [document.content for document in create.await_args.args[1]] == ["same", "same"]


@pytest.mark.parametrize("error", [RuntimeError("failed"), asyncio.CancelledError()])
async def test_failed_or_cancelled_seed_stops_without_replay_or_success(writer, error):
    create, actor = writer
    create.side_effect = error
    docs = [KnowledgeBaseSeedDoc(file_name=str(i), content=f"content {i}") for i in range(3)]
    with pytest.raises(type(error)) as caught:
        await seed_documents.index_seed_texts("kb", docs, actor, embedding_model_name="model")
    assert caught.value is error and create.await_count == 1
