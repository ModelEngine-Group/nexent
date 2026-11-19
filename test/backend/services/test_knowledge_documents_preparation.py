# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-PREPARE-02/03 keep source preparation out of model execution."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.agentos import ModelMetadata
from contracts.agentos_knowledge import ObjectReference
from management.services.knowledge_base import documents as module
from nexent.storage.errors import DeadlineExceeded, InvalidInput, ScopeDenied

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def preparation(mocker):
    actor = ServicePrincipal('operator', 'tenant-a')
    row = {'knowledge_id': 1, 'index_name': 'kb', 'embedding_model_id': 2, 'tenant_id': actor.tenant_id,
               'knowledge_sources': 'elasticsearch', 'deletion_request': None}
    reader = SimpleNamespace(knowledge=Mock(return_value=row))
    model = ModelMetadata(model_id=2, model_type='multi_embedding', display_name='Display name', revision='r1',
                          qualified_name='repo/model')
    client = SimpleNamespace(get_model=AsyncMock(return_value=model))
    events, contexts = [], []

    async def blocking(name, action, *args, **kwargs):
        kwargs.pop('lane'); kwargs.pop('owner')
        contexts.append(kwargs['context'])
        return action(*args, **kwargs)

    mocker.patch.object(module, 'run_blocking', side_effect=blocking)
    mocker.patch.object(module, 'time', SimpleNamespace(strftime=time.strftime, gmtime=lambda: time.gmtime(1234)))
    ref = ObjectReference(space='files', key='images_in_attachments/a.png', version='etag:one', sha256='a' * 64)
    pin = mocker.patch.object(module, 'pin_document_image', side_effect=lambda *args, **kwargs: events.append('pin') or ref)

    async def append(*args, **kwargs):
        events.append('append')
        contexts.append(kwargs['context'])
        return len(args[1])

    append = mocker.patch.object(module, 'append_documents', new=AsyncMock(side_effect=append))
    return SimpleNamespace(**locals())


async def test_original_source_fields_empty_text_images_and_model_version_are_preserved(preparation):
    s = preparation
    data = [{'content': '', 'path_or_url': '/dir/a.txt', 'source_type': 'local', 'file_size': 8,
                 'metadata': {'title': 'Title', 'languages': ['zh', 'en'], 'author': None,
                           'date': None, 'creation_date': None}}, 'ignored',
            {'content': 'caption', 'filename': 'image.png', 'metadata': {'process_source': 'UniversalImageExtractor',
                                                                   'image_url': 'images_in_attachments/a.png'}}]
    result = await module.index_documents('kb', data, s.actor, reader=s.reader, client=s.client)
    assert result == {'success': True, 'message': 'Successfully indexed 2 documents', 'total_indexed': 2, 'total_submitted': 2}
    assert s.events == ['pin', 'append']
    call = s.append.await_args
    assert call.args[0] == 'kb' and call.args[2] == s.actor
    first, picture = call.args[1]
    assert first.content == '' and first.image_ref is None
    assert first.metadata == {'title': 'Title', 'filename': 'a.txt', 'path_or_url': '/dir/a.txt', 'source_type': 'local',
        'language': 'zh', 'author': None, 'date': None, 'file_size': 8, 'create_time': None,
        'languages': ['zh', 'en'], 'process_source': 'Unstructured', 'embedding_model_name': 'repo/model'}
    assert picture.image_ref == s.ref and picture.content == 'caption'
    assert picture.metadata['filename'] == 'image.png' and picture.metadata['language'] == 'null'
    assert picture.metadata['date'] == '1970-01-01' and picture.metadata['create_time'] == '1970-01-01T00:20:34'
    assert 'image_bytes' not in picture.metadata and 'image_url' not in picture.metadata
    assert call.kwargs['model_binding'].model_id == 2 and call.kwargs['model_binding'].revision == 'r1'
    assert all(context is s.contexts[0] for context in s.contexts)
    s.client.get_model.assert_awaited_once_with(2, s.actor.user_id, s.actor.tenant_id)
    assert s.contexts[0].cancelled.is_set()


@pytest.mark.parametrize('phase', ['resource', 'model', 'image'])
async def test_preparation_error_never_submits_documents_or_retries(preparation, phase):
    s = preparation
    error = ScopeDenied()
    if phase == 'resource':
        s.reader.knowledge.side_effect = error
    elif phase == 'model':
        s.client.get_model.side_effect = error
    else:
        s.pin.side_effect = error
    with pytest.raises(ScopeDenied) as caught:
        await module.index_documents('kb', [{'content': 'text', 'metadata': {'image_url': 'images_in_attachments/a.png'}}],
                                     s.actor, reader=s.reader, client=s.client)
    assert caught.value is error
    s.append.assert_not_called()
    assert s.client.get_model.await_count <= 1 and s.pin.call_count <= 1


@pytest.mark.parametrize('changes', [{'model_id': 3}, {'model_type': 'llm'}, {'qualified_name': None}])
async def test_inconsistent_or_missing_model_identity_rejected_before_image_io(preparation, changes):
    s = preparation
    s.client.get_model.return_value = s.model.model_copy(update=changes)
    with pytest.raises(InvalidInput):
        await module.index_documents('kb', [{'content': 'text'}], s.actor, reader=s.reader, client=s.client)
    s.pin.assert_not_called()
    s.append.assert_not_called()


async def test_parent_deadline_cancels_model_query_without_append(preparation):
    s = preparation
    ended = asyncio.Event()

    async def waiting(*args):
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    s.client.get_model.side_effect = waiting
    with pytest.raises(DeadlineExceeded):
        await module.index_documents('kb', [{'content': 'text'}], s.actor,
                                     reader=s.reader, client=s.client, operation_seconds=.05)
    assert ended.is_set() and s.contexts[0].cancelled.is_set()
    s.append.assert_not_called()


async def test_empty_documents_still_require_current_edit_access_without_model_or_append(preparation):
    s = preparation
    result = await module.index_documents('kb', [], s.actor, reader=s.reader, client=s.client)
    assert result == {'success': True, 'message': 'No documents to index', 'total_indexed': 0, 'total_submitted': 0}
    assert s.reader.knowledge.call_count == 1
    s.client.get_model.assert_not_called()
    s.append.assert_not_called()


async def test_image_cancellation_is_not_wrapped_or_replayed(preparation):
    s = preparation
    error = asyncio.CancelledError()
    s.pin.side_effect = error
    with pytest.raises(asyncio.CancelledError) as caught:
        await module.index_documents('kb', [{'content': 'caption', 'metadata': {'image_url': 'images_in_attachments/a.png'}}],
                                     s.actor, reader=s.reader, client=s.client)
    assert caught.value is error and s.pin.call_count == 1 and s.contexts[0].cancelled.is_set()
    s.append.assert_not_called()


async def test_caller_owned_cancel_signal_is_preserved(preparation):
    from threading import Event
    from time import monotonic

    from nexent.storage.models import OperationContext

    s = preparation
    parent = Event()
    context = OperationContext('caller-preparation', monotonic() + 5, cancelled=parent)
    await module.index_documents('kb', [{'content': 'text'}], s.actor, reader=s.reader, client=s.client, context=context)
    assert all(value is context for value in s.contexts) and not parent.is_set()
