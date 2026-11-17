# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DELETE-PUBLIC-03: ordinary HTTP contracts with controlled service boundaries."""

from unittest.mock import AsyncMock, Mock

import pytest
from nexent.storage.errors import ScopeDenied

from test.backend.app.test_vectordatabase_app import client


@pytest.fixture
def boundary(monkeypatch):
    from management.api.knowledge_base import vectordatabase as module

    monkeypatch.setattr(module, 'get_current_user_id', lambda _: ('editor', 'tenant'))
    monkeypatch.setattr(module, 'require_knowledge_base_edit_permission', Mock())
    audit = Mock()
    monkeypatch.setattr(module, 'record_security_event', audit)
    service = AsyncMock(return_value={'status': 'success', 'scope': 'full', 'deleted_es_count': 3,
                                      'deleted_minio': True, 'source_available': False, 'lifecycle_deleted': True})
    monkeypatch.setattr(module.ElasticSearchService, 'delete_document_by_scope', service)
    redis = Mock(side_effect=AssertionError('Document deletion must not open Redis'))
    monkeypatch.setattr('management.services.knowledge_base.task_state.get_redis_service', redis)
    return module, service, audit, redis


@pytest.mark.parametrize('params,path,file_id', [
    ({'path_or_url': 's3://bucket/key'}, 's3://bucket/key', None),
    ({'file_id': 'b' * 32}, None, 'b' * 32),
    ({'path_or_url': 'old-path', 'file_id': 'b' * 32}, 'old-path', 'b' * 32),
])
def test_public_route_preserves_query_and_actor_and_requests_tag_cleanup(boundary, params, path, file_id):
    _, service, audit, redis = boundary
    response = client.delete('/indices/kb/documents', params=params)
    assert response.status_code == 200
    assert response.json()['deleted_es_count'] == 3
    assert response.json()['redis_cleanup']['total_deleted'] == 0
    service.assert_awaited_once_with('kb', path, 'full', requested_by='editor', tenant_id='tenant',
                                     file_id=file_id, remove_tags=True)
    assert audit.call_args.kwargs['details'] == {'index_name': 'kb', 'path_or_url': path, 'file_id': file_id, 'scope': 'full'}
    redis.assert_not_called()


def test_missing_identity_is_a_client_error_without_service_call(boundary):
    _, service, audit, _ = boundary
    assert client.delete('/indices/kb/documents').status_code == 400
    service.assert_not_called()
    audit.assert_not_called()


@pytest.mark.parametrize('error,code', [(ValueError('invalid scope'), 400), (ScopeDenied(), 403),
                                       (PermissionError('denied'), 403), (RuntimeError('failed'), 500)])
def test_errors_keep_http_mapping(boundary, error, code):
    _, service, _, _ = boundary
    service.side_effect = error
    assert client.delete('/indices/kb/documents', params={'file_id': 'b' * 32}).status_code == code


@pytest.mark.parametrize('scope', ['source_only', 'full'])
def test_pending_and_source_only_do_not_get_a_terminal_cleanup_summary(boundary, scope):
    _, service, _, redis = boundary
    expected = {'status': 'pending', 'scope': scope, 'deletion_pending': True}
    service.return_value = expected
    response = client.delete('/indices/kb/documents', params={'path_or_url': 'key', 'scope': scope})
    assert response.status_code == 200 and response.json() == expected
    redis.assert_not_called()
