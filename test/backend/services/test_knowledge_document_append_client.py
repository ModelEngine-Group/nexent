# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management forwards bounded standard append batches without per-document HTTP calls."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge_documents import KnowledgeDocument, KnowledgeDocumentsAppended
from management.services.knowledge_base import document_append
from nexent.storage.errors import Conflict, DeadlineExceeded

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def writer(mocker):
    actor = ServicePrincipal("operator", "tenant-a")
    row = {"knowledge_id": 1, "index_name": "kb", "tenant_id": actor.tenant_id, "embedding_model_id": 2,
           "knowledge_sources": "elasticsearch", "deletion_request": None}
    reader = SimpleNamespace(knowledge=Mock(return_value=row))
    contexts = []

    async def blocking(name, action, *args, **kwargs):
        kwargs.pop("lane"); kwargs.pop("owner")
        contexts.append(kwargs["context"])
        return action(*args, **kwargs)

    mocker.patch.object(document_append, "run_blocking", side_effect=blocking)
    touch = mocker.patch.object(document_append, "_touch_activity")

    async def append(request, user, tenant):
        assert (user, tenant) == (actor.user_id, actor.tenant_id)
        size = len(request.documents)
        return KnowledgeDocumentsAppended(knowledge_id=1, total_submitted=size, total_indexed=size,
                                          chunk_ids=[str(i) for i in range(size)])

    client = SimpleNamespace(append_knowledge_documents=AsyncMock(side_effect=append))
    return SimpleNamespace(**locals())


async def test_management_uses_64_document_batches_and_one_final_activity_touch(writer):
    s = writer
    docs = [KnowledgeDocument(content=str(i)) for i in range(66)]
    assert await document_append.append_documents("kb", docs, s.actor, reader=s.reader, client=s.client) == 66
    calls = s.client.append_knowledge_documents.await_args_list
    assert [len(call.args[0].documents) for call in calls] == [64, 2]
    assert all(call.args[0].embedding_model.model_id == 2 for call in calls)
    assert all(call.args[0].embedding_batch_size is None for call in calls)
    assert s.touch.call_count == 1 and all(context is s.contexts[0] for context in s.contexts)


@pytest.mark.parametrize("batch,expected", [(2, 2), (100, 64)])
async def test_embedding_batch_setting_is_preserved_within_physical_batch_limit(writer, batch, expected):
    s = writer
    await document_append.append_documents("kb", [KnowledgeDocument(content="text")], s.actor,
        reader=s.reader, client=s.client, embedding_batch_size=batch)
    assert s.client.append_knowledge_documents.await_args.args[0].embedding_batch_size == expected


async def test_empty_request_has_no_resource_http_or_activity_side_effects(writer):
    s = writer
    assert await document_append.append_documents("kb", [], s.actor, reader=s.reader, client=s.client) == 0
    s.reader.knowledge.assert_not_called()
    s.client.append_knowledge_documents.assert_not_called()
    s.touch.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("later batch failed"), asyncio.CancelledError()])
async def test_failed_later_batch_is_not_replayed_and_does_not_touch_activity(writer, error):
    s = writer
    first = await s.client.append_knowledge_documents.side_effect(
        SimpleNamespace(documents=[1] * 64), s.actor.user_id, s.actor.tenant_id)
    s.client.append_knowledge_documents.side_effect = [first, error]
    with pytest.raises(type(error)) as caught:
        await document_append.append_documents("kb", [KnowledgeDocument(content="text")] * 65,
                                               s.actor, reader=s.reader, client=s.client)
    assert caught.value is error and s.client.append_knowledge_documents.await_count == 2
    s.touch.assert_not_called()


async def test_wrong_receipt_cannot_be_counted_as_success(writer):
    s = writer
    s.client.append_knowledge_documents.side_effect = None
    s.client.append_knowledge_documents.return_value = KnowledgeDocumentsAppended(
        knowledge_id=2, total_submitted=1, total_indexed=1, chunk_ids=["wrong"])
    with pytest.raises(Conflict):
        await document_append.append_documents("kb", [KnowledgeDocument(content="text")], s.actor,
                                               reader=s.reader, client=s.client)
    s.touch.assert_not_called()


@pytest.mark.parametrize("as_dict", [False, True])
async def test_confirmed_image_skip_is_counted_without_faking_an_indexed_document(writer, as_dict):
    s = writer
    s.client.append_knowledge_documents.side_effect = None
    s.client.append_knowledge_documents.return_value = KnowledgeDocumentsAppended(
        knowledge_id=1, total_submitted=2, total_indexed=1, total_skipped=1, chunk_ids=["text"])
    documents = [KnowledgeDocument(content="text"),
                 KnowledgeDocument(content="caption", metadata={"process_source": "UniversalImageExtractor"})]
    if as_dict:
        documents = [doc.model_dump() for doc in documents]
    assert await document_append.append_documents("kb", documents, s.actor, reader=s.reader, client=s.client) == 1
    assert s.touch.call_count == 1


async def test_text_cannot_be_hidden_as_a_successful_image_skip(writer):
    s = writer
    s.client.append_knowledge_documents.side_effect = None
    s.client.append_knowledge_documents.return_value = KnowledgeDocumentsAppended(
        knowledge_id=1, total_submitted=1, total_indexed=0, total_skipped=1, chunk_ids=[])
    with pytest.raises(Conflict):
        await document_append.append_documents("kb", [KnowledgeDocument(content="text")], s.actor,
                                               reader=s.reader, client=s.client)
    s.touch.assert_not_called()


async def test_activity_failure_retains_original_best_effort_semantics_without_replay(writer):
    s = writer
    s.touch.side_effect = RuntimeError("metadata unavailable")
    assert await document_append.append_documents("kb", [KnowledgeDocument(content="text")], s.actor,
                                                  reader=s.reader, client=s.client) == 1
    assert s.client.append_knowledge_documents.await_count == s.touch.call_count == 1


async def test_parent_deadline_cancels_rpc_and_marks_its_owned_context(writer):
    s = writer
    ended = asyncio.Event()

    async def hanging(*args):
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    s.client.append_knowledge_documents.side_effect = hanging
    with pytest.raises(DeadlineExceeded):
        await document_append.append_documents("kb", [KnowledgeDocument(content="text")], s.actor,
                                               reader=s.reader, client=s.client, operation_seconds=.05)
    assert ended.is_set() and s.contexts[0].cancelled.is_set()
    assert s.client.append_knowledge_documents.await_count == 1
    s.touch.assert_not_called()
