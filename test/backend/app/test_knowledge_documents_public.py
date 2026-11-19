# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-PUBLIC-01/02/03 cover the unchanged public document contract."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from management.api.knowledge_base import vectordatabase as module

from backend.http.server.exception_handlers import register_exception_handlers


@pytest.fixture
def public(mocker):
    app = FastAPI()
    app.include_router(module.router)
    register_exception_handlers(app)
    client = TestClient(app)
    events, contexts = [], []
    mocker.patch.object(module, 'get_current_user_id', return_value=('operator', 'tenant-a'))
    permission = mocker.patch.object(module, 'require_knowledge_base_edit_permission',
        side_effect=lambda *a: events.append('permission'))
    row = {'knowledge_id': 1, 'index_name': 'kb', 'ingroup_permission': 'PRIVATE', 'embedding_model_id': 2}
    record = mocker.patch.object(module, 'get_knowledge_record', return_value=row)
    quota = mocker.patch.object(module, '_check_personal_kb_quota_before_indexing',
        side_effect=lambda *a: events.append('quota'))

    async def blocking(name, action, *args, **kwargs):
        kwargs.pop('lane'); kwargs.pop('owner')
        contexts.append(kwargs['context'])
        return action(*args, **kwargs)

    worker = mocker.patch.object(module, 'run_blocking', side_effect=blocking)

    async def append(*args, **kwargs):
        events.append('append')
        return {'success': True, 'message': 'Successfully indexed 1 documents', 'total_indexed': 1, 'total_submitted': 1}

    index = mocker.patch.object(module, 'index_documents', new=AsyncMock(side_effect=append))
    native = mocker.patch.object(module, 'get_vector_db_core', side_effect=AssertionError('Native VDB constructed'))
    model = mocker.patch('management.services.model.resolver.get_embedding_model_by_id', side_effect=AssertionError('SDK model constructed'))
    yield SimpleNamespace(**locals())
    client.close()


@pytest.mark.parametrize('large', [False, True])
def test_document_header_is_tracking_only_and_original_input_reaches_standard_service(public, large, caplog):
    s = public
    body = [{'content': '', 'metadata': {'image_url': 'images_in_attachments/a.png'}, 'filename': 'a.png'}]
    with caplog.at_level('INFO', logger=module.logger.name):
        response = s.client.post('/indices/kb/documents', json=body, params={'large_mode': str(large).lower()},
                                 headers={'X-Task-Id': 'trace-only'})
    assert response.status_code == 200 and response.json() == {
        'success': True, 'message': 'Successfully indexed 1 documents', 'total_indexed': 1, 'total_submitted': 1}
    assert s.events == ['permission', 'quota', 'append']
    call = s.index.await_args
    assert call.args[:2] == ('kb', body)
    assert (call.args[2].user_id, call.args[2].tenant_id) == ('operator', 'tenant-a')
    assert set(call.kwargs) == {'context'} and call.kwargs['context'] is s.contexts[0]
    assert s.contexts[0].cancelled.is_set()
    s.quota.assert_called_once_with(body, s.row, 'tenant-a', 'operator')
    s.native.assert_not_called(); s.model.assert_not_called()
    assert 'trace-only' in caplog.text


def test_empty_body_keeps_original_zero_counts(public):
    s = public
    result = {'success': True, 'message': 'No documents to index', 'total_indexed': 0, 'total_submitted': 0}
    s.index.side_effect = None
    s.index.return_value = result
    response = s.client.post('/indices/kb/documents', json=[])
    assert response.status_code == 200 and response.json() == result
    assert s.index.await_args.args[1] == []


def test_edit_rejection_prevents_quota_and_execution(public):
    s = public
    s.permission.side_effect = HTTPException(status_code=403, detail='No permission to modify this knowledge base')
    response = s.client.post('/indices/kb/documents', json=[{'content': 'text'}])
    assert response.status_code == 403 and response.json()['message'] == 'No permission to modify this knowledge base'
    s.record.assert_not_called(); s.quota.assert_not_called(); s.index.assert_not_awaited()


def test_original_quota_rejection_remains_structured_and_prevents_execution(public):
    s = public
    error = AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED, 'quota exceeded')
    s.quota.side_effect = error
    response = s.client.post('/indices/kb/documents', json=[{'content': 'text'}])
    assert response.status_code == error.http_status and response.json()['message'] == 'quota exceeded'
    s.index.assert_not_awaited()


@pytest.mark.parametrize('body', [{'content': 'text'}, [1], None])
def test_existing_list_of_dict_validation_stays_422(public, body):
    s = public
    response = s.client.post('/indices/kb/documents', json=body)
    assert response.status_code == 422
    s.permission.assert_not_called(); s.index.assert_not_awaited()


def test_preparation_error_preserves_public_500_without_retry(public):
    s = public
    s.index.side_effect = ValueError('Invalid document format')
    response = s.client.post('/indices/kb/documents', json=[{'content': 'text'}])
    assert response.status_code == 500 and response.json() == {'message': 'Error indexing documents: Invalid document format'}
    assert s.index.await_count == 1


def test_precheck_timeout_never_starts_standard_preparation(public, mocker, caplog):
    s = public
    mocker.patch.object(module, 'DOCUMENT_INDEX_SECONDS', 0.02)

    async def blocked(*args, **kwargs):
        s.contexts.append(kwargs['context'])
        await asyncio.Event().wait()

    s.worker.side_effect = blocked
    response = s.client.post('/indices/kb/documents', json=[{'content': 'text'}])
    assert response.status_code == 500 and s.worker.await_count == 1
    assert s.contexts[0].cancelled.is_set()
    s.index.assert_not_awaited()
    records = [r for r in caplog.records if 'knowledge_documents_public_timeout' in r.message]
    assert len(records) == 1 and records[0].levelname == 'WARNING'


async def test_request_cancellation_propagates_and_sets_context(public):
    s = public
    s.index.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await module.create_index_documents(index_name='kb', data=[], authorization=None, task_id=None, large_mode=False)
    assert s.contexts[0].cancelled.is_set() and s.index.await_count == 1
