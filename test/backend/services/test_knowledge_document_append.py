# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-APPEND-01/02/03 preserve physical append and inference ordering."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agentos import ModelMetadata, ModelResult
from contracts.knowledge_chunk_mutation import ChunkMutationGrant
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from contracts.knowledge_documents import KnowledgeDocument, KnowledgeDocumentsAppend
from nexent.storage.errors import Conflict, DeadlineExceeded, InvalidInput, ScopeDenied
from nexent.storage.models import WriteReceipt
from runtime.knowledge_base import document_append as module
from runtime.knowledge_base.chunk_write import ChunkMutationService
from runtime.knowledge_base.document_append import KnowledgeDocumentAppender

from test.backend.services.test_knowledge_chunk_creation import context
from test.backend.services.test_knowledge_chunk_creation import (
    creation as creation,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_creation import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_creation import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)


@pytest.fixture
def append(creation, mocker):
    s = creation
    rows, events, opened = {}, [], []
    s.models.get = AsyncMock(return_value=ModelMetadata(model_id=2, model_type="embedding", display_name="model", revision="r1"))

    async def invoke(payload, actor):
        events.append("model")
        return ModelResult(revision="r1", output=[[1, 0, 0] for _ in payload.input])

    s.models.invoke.side_effect = invoke
    s.vectors.get.side_effect = lambda key, **kwargs: rows.get(key.key)

    def put(record, **kwargs):
        events.append("put")
        rows[record.key.key] = record
        return WriteReceipt("put", True)

    s.vectors.put.side_effect = put

    @contextmanager
    def records(actor, *, context, **namespace):
        assert actor == s.s.actor and not namespace
        opened.append(True)
        yield s.s.mutation.records

    async def authorize(request, user, tenant):
        assert (user, tenant) == (s.s.actor.user_id, s.s.actor.tenant_id)
        return ChunkMutationGrant(**request.model_dump(), collection="collection", resource_tenant_id=tenant,
                                  revision="a" * 64, embedding_model_id=2)

    client = SimpleNamespace(authorize_knowledge_chunk_mutation=AsyncMock(side_effect=authorize))
    service = KnowledgeDocumentAppender(ChunkMutationService(client, s.models, records=records, creation_ports=s.ports))
    batch_setting = mocker.patch.object(module, "read_document_embedding_batch", create=True, return_value=10)
    request = KnowledgeDocumentsAppend(knowledge_id=1, resource_revision="a" * 64, embedding_model={"model_id": 2},
        documents=[KnowledgeDocument(content="same", metadata={"id": "duplicate", "title": "original"}) for _ in range(2)])
    return SimpleNamespace(**locals())


async def test_default_batch_uses_authorized_resource_setting_before_inference(append):
    a = append
    a.batch_setting.return_value = 1
    result = await a.service.append(a.request, a.s.s.actor, context=context())
    assert result.total_indexed == 2
    assert a.events == ["model", "model", "put", "put"]
    assert a.batch_setting.call_count == 1
    assert a.batch_setting.call_args.args == (a.s.s.actor, a.s.s.actor.tenant_id, "embedding")


async def test_explicit_batch_never_reads_tenant_setting(append):
    a = append
    request = a.request.model_copy(update={"embedding_batch_size": 2})
    await a.service.append(request, a.s.s.actor, context=context())
    a.batch_setting.assert_not_called()
    assert a.events == ["model", "put", "put"]


async def test_configuration_failure_prevents_model_and_write_without_replay(append):
    a = append
    a.batch_setting.side_effect = Conflict()
    with pytest.raises(Conflict):
        await a.service.append(a.request, a.s.s.actor, context=context())
    assert a.batch_setting.call_count == 1 and not a.events and not a.opened


async def test_asset_configuration_uses_resource_namespace_without_impersonating_actor(append):
    from contracts.constants.constants import ASSET_OWNER_TENANT_ID

    a = append
    original = a.client.authorize_knowledge_chunk_mutation.side_effect

    async def asset(*args):
        grant = await original(*args)
        return grant.model_copy(update={"resource_tenant_id": ASSET_OWNER_TENANT_ID})

    a.client.authorize_knowledge_chunk_mutation.side_effect = asset
    a.batch_setting.side_effect = Conflict()
    with pytest.raises(Conflict):
        await a.service.append(a.request, a.s.s.actor, context=context())
    assert a.batch_setting.call_args.args == (a.s.s.actor, ASSET_OWNER_TENANT_ID, "embedding")
    assert not a.events and not a.opened


async def test_configuration_wait_shares_parent_deadline_and_does_not_start_inference(append, mocker):
    import asyncio
    from time import monotonic

    from nexent.storage.models import OperationContext

    a = append
    ended = asyncio.Event()

    async def waiting(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    blocking = mocker.patch.object(module, "run_blocking", side_effect=waiting)
    with pytest.raises(DeadlineExceeded):
        await a.service.append(a.request, a.s.s.actor, context=OperationContext("batch-config-timeout", monotonic() + .05))
    assert ended.is_set() and blocking.await_count == 1 and not a.events and not a.opened


async def test_duplicate_display_ids_append_two_physical_records_after_all_inference(append):
    a = append
    result = await a.service.append(a.request, a.s.s.actor, context=context())
    assert result.total_indexed == result.total_submitted == len(a.rows) == 2
    assert len(set(result.chunk_ids)) == 2 and set(result.chunk_ids) == set(a.rows)
    assert a.events == ["model", "put", "put"]
    assert all(row.payload["location"][PUBLIC_CHUNK_SOURCE_KEY] == {"id": "duplicate", "title": "original"}
               for row in a.rows.values())
    assert await a.s.db(a.s.s.mutation.standalone_count, context=context()) == 2


async def test_generated_display_ids_can_repeat_without_collapsing_empty_text_records(append):
    a = append
    a.request = a.request.model_copy(update={"documents": [KnowledgeDocument(content="")] * 2})
    result = await a.service.append(a.request, a.s.s.actor, context=context())
    assert result.total_indexed == len(a.rows) == 2
    ids = [row.payload["location"][PUBLIC_CHUNK_SOURCE_KEY]["id"] for row in a.rows.values()]
    assert ids[0] == ids[1] and len(ids[0]) <= 20
    assert a.s.models.invoke.await_args.args[0].input == ["", ""]
    assert a.events == ["model", "put", "put"]


async def test_later_model_subbatch_failure_never_starts_any_physical_write(append):
    a = append
    a.request = a.request.model_copy(update={"embedding_batch_size": 1})
    error = RuntimeError("second inference failed")
    a.s.models.invoke.side_effect = [ModelResult(revision="r1", output=[[1, 0, 0]]), error]
    with pytest.raises(RuntimeError) as caught:
        await a.service.append(a.request, a.s.s.actor, context=context())
    assert caught.value is error and not a.rows and not a.opened
    assert a.s.models.invoke.await_count == 2


async def test_revoked_grant_after_inference_prevents_records_and_vectors(append):
    a = append
    first = a.client.authorize_knowledge_chunk_mutation.side_effect
    count = 0

    async def revoke(*args):
        nonlocal count
        count += 1
        if count > 1:
            raise ScopeDenied()
        return await first(*args)

    a.client.authorize_knowledge_chunk_mutation.side_effect = revoke
    with pytest.raises(ScopeDenied):
        await a.service.append(a.request, a.s.s.actor, context=context())
    assert not a.rows and not a.opened and a.s.models.invoke.await_count == 1


@pytest.mark.parametrize("output,revision", [([], "r1"), ([[0, 0, 0], [0, 0, 0]], "r1"),
                                            ([[1, 0], [1, 0]], "r1"), ([[1, 0, 0], [1, 0, 0]], "stale")])
async def test_invalid_batch_vectors_or_revision_never_open_write_ports(append, output, revision):
    a = append
    a.s.models.invoke.side_effect = None
    a.s.models.invoke.return_value = ModelResult(revision=revision, output=output)
    with pytest.raises((InvalidInput, Conflict)):
        await a.service.append(a.request, a.s.s.actor, context=context())
    assert not a.rows and not a.opened and a.s.models.invoke.await_count == 1


async def test_model_timeout_cancels_without_writes_or_replay(append):
    import asyncio
    from time import monotonic

    from nexent.storage.models import OperationContext

    a = append
    ended = asyncio.Event()

    async def hanging(*args):
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    a.s.models.invoke.side_effect = hanging
    with pytest.raises(DeadlineExceeded):
        await a.service.append(a.request, a.s.s.actor, context=OperationContext("batch-timeout", monotonic() + .05))
    assert ended.is_set() and not a.opened and not a.rows
    assert a.s.models.invoke.await_count == 1
