# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The public summary adapter preserves existing SSE events with valid JSON payloads."""

import json
from unittest.mock import AsyncMock

import pytest

from test.backend.app.test_knowledge_summary_app import client


@pytest.mark.parametrize('text', ['simple', '中文"\n\\'])
def test_summary_stream_preserves_characters_and_completes(monkeypatch, text):
    from management.api.knowledge_base import knowledge_summary as module

    service = AsyncMock()
    service.generate.return_value = text
    monkeypatch.setattr(module, 'KnowledgeSummaryService', lambda: service)
    response = client.post('/summary/kb-one/auto_summary?model_id=5&batch_size=50',
                           headers={'Authorization': 'Bearer controlled'})
    assert response.status_code == 200 and response.headers['content-type'].startswith('text/event-stream')
    events = [json.loads(line.removeprefix('data: ')) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1] == {'status': 'completed'}
    assert ''.join(event['message'] for event in events[:-1]) == text
    assert all(event['status'] == 'success' for event in events[:-1])
    service.generate.assert_awaited_once_with(index_name='kb-one', batch_size=50, model_id=5,
        user_id='test_user_id', tenant_id='test_tenant_id', language='en')


def test_stream_failure_remains_an_error_event(monkeypatch):
    from management.api.knowledge_base import knowledge_summary as module

    class Broken:
        def __iter__(self):
            raise RuntimeError('stream "failure"')
    service = AsyncMock()
    service.generate.return_value = Broken()
    monkeypatch.setattr(module, 'KnowledgeSummaryService', lambda: service)
    response = client.post('/summary/kb/auto_summary?model_id=5')
    event = json.loads(response.text.strip().removeprefix('data: '))
    assert event == {'status': 'error', 'message': 'stream "failure"'}


def test_missing_knowledge_keeps_404_and_timeout_does_not_log_duplicate_error(monkeypatch, caplog):
    from management.api.knowledge_base import knowledge_summary as module
    from nexent.storage.errors import DeadlineExceeded, NotFound

    service = AsyncMock()
    monkeypatch.setattr(module, 'KnowledgeSummaryService', lambda: service)
    service.generate.side_effect = NotFound()
    response = client.post('/summary/missing/auto_summary?model_id=5')
    assert response.status_code == 404 and response.json()['detail'] == "Knowledge base 'missing' not found"
    service.generate.side_effect = DeadlineExceeded()
    response = client.post('/summary/missing/auto_summary?model_id=5')
    assert response.status_code == 500
    assert json.loads(response.text.strip().removeprefix('data: '))['status'] == 'error'
    assert not any(record.levelname == 'ERROR' for record in caplog.records)


def test_former_dependency_query_contract_does_not_override_actual_tenant(monkeypatch):
    from management.api.knowledge_base import knowledge_summary as module

    service = AsyncMock()
    service.generate.return_value = 'x'
    monkeypatch.setattr(module, 'KnowledgeSummaryService', lambda: service)
    response = client.post('/summary/kb/auto_summary?model_id=5&db_type=elasticsearch&tenant_id=foreign')
    assert response.status_code == 200
    assert service.generate.call_args.kwargs['tenant_id'] == 'test_tenant_id'
    invalid = client.post('/summary/kb/auto_summary?model_id=5&db_type=invalid')
    assert invalid.status_code == 422
    unsupported = client.post('/summary/kb/auto_summary?model_id=5&db_type=datamate&tenant_id=foreign')
    assert unsupported.status_code == 500
    service.generate.assert_awaited_once()


def test_public_query_schema_preserves_provider_and_tenant_fields(monkeypatch):
    from management.api.knowledge_base import knowledge_summary as module

    service = AsyncMock()
    monkeypatch.setattr(module, 'KnowledgeSummaryService', lambda: service)
    operation = client.app.openapi()['paths']['/summary/{index_name}/auto_summary']['post']
    parameters = {parameter['name']: parameter for parameter in operation['parameters']}
    assert parameters['db_type']['in'] == parameters['tenant_id']['in'] == 'query'
    assert parameters['db_type']['schema']['default'] == 'elasticsearch'
    response = client.post('/summary/kb/auto_summary?db_type=unknown')
    assert response.status_code == 422
    service.generate.assert_not_awaited()
