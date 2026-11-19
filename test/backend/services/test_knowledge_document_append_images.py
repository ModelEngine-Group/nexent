# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-IMAGE-APPEND-03/04 keep image inference and skip semantics."""

import base64
import hashlib

import pytest
from contracts.agentos import ModelMetadata, ModelResult
from contracts.agentos_knowledge import ObjectReference
from contracts.knowledge_documents import KnowledgeDocument
from nexent.storage.errors import DeadlineExceeded, InvalidInput, ScopeDenied
from runtime.knowledge_base import document_append as module

from test.backend.services.test_knowledge_document_append import (
    append as append,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_document_append import (
    context,
)
from test.backend.services.test_knowledge_document_append import (
    creation as creation,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_document_append import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_document_append import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)


@pytest.fixture
def images(append, mocker):
    a = append
    a.raw = b'\x89PNG\r\n\x1a\noriginal PNG bytes'
    a.ref = ObjectReference(space='files', key='images_in_attachments/a.png', version='etag:one',
                            sha256=hashlib.sha256(a.raw).hexdigest())
    a.image_reader = mocker.patch.object(module, 'read_pinned_object_image', return_value=a.raw)
    a.s.models.get.return_value = ModelMetadata(model_id=2, model_type='multi_embedding', display_name=None, revision='r1')
    a.picture = {'content': 'caption remains', 'metadata': {'process_source': 'UniversalImageExtractor', 'filename': 'a.png'},
                 'image_ref': a.ref}
    return a


async def test_mixed_image_and_text_keep_input_correspondence_and_caption(images):
    a = images
    docs = [KnowledgeDocument(content='first text'), KnowledgeDocument(**a.picture), KnowledgeDocument(content='last text')]
    a.request = a.request.model_copy(update={'documents': docs})

    async def invoke(payload, actor):
        a.events.append('model-' + payload.input_type)
        assert actor == a.s.s.actor
        if payload.input_type == 'image':
            assert payload.input == ['data:image/png;base64,' + base64.b64encode(a.raw).decode('ascii')]
        vector = [0, 1, 0] if payload.input_type == 'image' else [1, 0, 0]
        return ModelResult(revision='r1', output=[vector for _ in payload.input])

    a.s.models.invoke.side_effect = invoke
    result = await a.service.append(a.request, a.s.s.actor, context=context())
    assert result.total_submitted == result.total_indexed == 3 and result.total_skipped == 0
    assert a.events == ['model-text', 'model-image', 'put', 'put', 'put']
    rows = list(a.rows.values())
    assert [row.payload['content'] for row in rows] == ['first text', 'caption remains', 'last text']
    assert [tuple(row.vector) for row in rows] == [(1., 0., 0.), (0., 1., 0.), (1., 0., 0.)]
    assert all(base64.b64encode(a.raw).decode('ascii') not in str(row.payload) for row in rows)
    a.image_reader.assert_called_once_with(a.ref, user_id=a.s.s.actor.user_id,
                                         tenant_id=a.s.s.actor.tenant_id, context=a.image_reader.call_args.kwargs['context'])


@pytest.mark.parametrize('failure', ['read', 'model'])
async def test_image_error_does_not_write_text_prefix_or_retry(images, failure):
    a = images
    a.request = a.request.model_copy(update={'documents': [KnowledgeDocument(content='valid text'), KnowledgeDocument(**a.picture)]})
    error = RuntimeError('image failure')
    if failure == 'read':
        a.image_reader.side_effect = error
    else:
        a.s.models.invoke.side_effect = [ModelResult(revision='r1', output=[[1, 0, 0]]), error]
    with pytest.raises(RuntimeError) as caught:
        await a.service.append(a.request, a.s.s.actor, context=context())
    assert caught.value is error and not a.rows and not a.opened
    assert a.image_reader.call_count == 1 and a.s.models.invoke.await_count == (0 if failure == 'read' else 2)


@pytest.mark.parametrize('kind', ['text_model', 'missing', 'empty'])
async def test_original_image_skips_are_counted_without_caption_embedding(images, kind):
    a = images
    if kind == 'text_model':
        a.s.models.get.return_value = ModelMetadata(model_id=2, model_type='embedding', display_name=None, revision='r1')
    elif kind == 'missing':
        a.picture.pop('image_ref')
    else:
        a.image_reader.return_value = b''
    a.request = a.request.model_copy(update={'documents': [KnowledgeDocument(**a.picture)]})
    result = await a.service.append(a.request, a.s.s.actor, context=context())
    assert result.total_submitted == result.total_skipped == 1 and result.total_indexed == 0 and not result.chunk_ids
    assert not a.events and not a.opened and a.s.models.invoke.await_count == 0
    assert a.image_reader.call_count == (1 if kind == 'empty' else 0)


async def test_foreign_object_is_rejected_before_reading_or_inference(images):
    a = images
    a.picture['image_ref'] = a.ref.model_copy(update={'key': 'attachments/other/private.png'})
    a.request = a.request.model_copy(update={'documents': [KnowledgeDocument(**a.picture)]})
    with pytest.raises(ScopeDenied):
        await a.service.append(a.request, a.s.s.actor, context=context())
    a.image_reader.assert_not_called()
    assert not a.events and not a.opened


async def test_non_files_reference_is_rejected_before_object_io(images):
    a = images
    a.picture['image_ref'] = a.ref.model_copy(update={'space': 'private'})
    with pytest.raises((ValueError, InvalidInput)):
        request = a.request.model_copy(update={'documents': [KnowledgeDocument(**a.picture)]})
        await a.service.append(request, a.s.s.actor, context=context())
    a.image_reader.assert_not_called()


async def test_image_wait_is_cancelled_by_parent_budget_without_caption_fallback(images, mocker):
    import asyncio
    from time import monotonic

    from nexent.storage.models import OperationContext

    a = images
    request = a.request.model_copy(update={'documents': [KnowledgeDocument(**a.picture)], 'embedding_batch_size': 10})
    ended = asyncio.Event()

    async def waiting(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    blocking = mocker.patch.object(module, 'run_blocking', side_effect=waiting)
    with pytest.raises(DeadlineExceeded):
        await a.service.append(request, a.s.s.actor, context=OperationContext('image-timeout', monotonic() + .05))
    assert ended.is_set() and blocking.await_count == 1 and not a.events and not a.opened
    assert blocking.await_args.kwargs['context'].cancelled.is_set()
