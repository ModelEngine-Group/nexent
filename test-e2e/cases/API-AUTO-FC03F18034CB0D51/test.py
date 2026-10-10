from __future__ import annotations

from http import HTTPStatus

import pytest
from fastapi import HTTPException

from apps import vectordatabase_app as vdb_app


class _FakeDeletionService:
    def __init__(self) -> None:
        self.result: dict = {}
        self.calls = 0

    async def delete_document_by_scope(self, index_name, path_or_url, scope, vdb_core, **kwargs):
        self.calls += 1
        return dict(self.result)

    def delete_lifecycle_record_without_object(self, lifecycle_record, requested_by=None):
        return {
            'status': 'success',
            'scope': 'full',
            'lifecycle_deleted': True,
            'message': 'Lifecycle record deleted; no storage object was created.',
        }


class _FakeRedisService:
    def __init__(self) -> None:
        self.calls = 0
        self.cleanup_result: dict = {
            'total_deleted': 4,
            'celery_tasks_deleted': 2,
            'cache_keys_deleted': 2,
            'errors': [],
        }
        self.raise_error: Exception | None = None

    def delete_document_records(self, index_name, path_or_url):
        self.calls += 1
        if self.raise_error is not None:
            raise self.raise_error
        return dict(self.cleanup_result)


def _raise_permission_denied(index_name, user_id, tenant_id):
    raise PermissionError('no edit permission')


@pytest.mark.asyncio
@pytest.mark.case_id('API-AUTO-FC03F18034CB0D51')
@pytest.mark.stage('D2')
async def test_document_deletion_redis_cleanup_sink(monkeypatch):
    monkeypatch.setattr(vdb_app, 'get_current_user_id', lambda authorization: ('user-1', 'tenant-1'))
    monkeypatch.setattr(vdb_app, 'require_knowledge_base_edit_permission', lambda index_name, user_id, tenant_id: None)
    monkeypatch.setattr(
        'services.tag_management_service.TagManagementService.cleanup_document_assignments',
        lambda *args, **kwargs: None,
    )

    async def run(*, result=None, redis_result=None, redis_error=None,
                  index_name='idx-run', path_or_url='doc/run.txt', file_id=None, scope='full'):
        service = _FakeDeletionService()
        service.result = result or {}
        redis_service = _FakeRedisService()
        if redis_result is not None:
            redis_service.cleanup_result = redis_result
        redis_service.raise_error = redis_error
        monkeypatch.setattr(vdb_app, 'ElasticSearchService', service)
        monkeypatch.setattr(vdb_app, 'get_redis_service', lambda: redis_service)
        response = await vdb_app.delete_documents(
            index_name=index_name,
            path_or_url=path_or_url,
            file_id=file_id,
            scope=scope,
            vdb_core=None,
            authorization='Bearer fake-token',
        )
        return response, service, redis_service

    response, service, redis_service = await run(result={
        'status': 'success',
        'scope': 'full',
        'message': 'Documents deleted successfully',
        'redis_cleanup': {
            'total_deleted': 5,
            'celery_tasks_deleted': 3,
            'cache_keys_deleted': 2,
            'errors': [],
        },
    })
    assert service.calls == 1
    assert redis_service.calls == 0
    assert response['redis_cleanup']['total_deleted'] == 5
    assert 'Cleaned up 5 Redis records (3 tasks, 2 cache keys).' in response['message']

    response, service, redis_service = await run(result={
        'status': 'pending',
        'scope': 'full',
        'deletion_pending': True,
        'message': 'Deletion requested; waiting for Celery tasks to stop.',
    })
    assert service.calls == 1
    assert redis_service.calls == 0
    assert response['deletion_pending'] is True
    assert 'redis_cleanup' not in response
    assert 'Cleaned up' not in response.get('message', '')

    response, service, redis_service = await run(
        result={'status': 'success', 'message': 'Documents deleted successfully'},
        redis_result={
            'total_deleted': 4,
            'celery_tasks_deleted': 2,
            'cache_keys_deleted': 2,
            'errors': [],
        },
    )
    assert service.calls == 1
    assert redis_service.calls == 1
    assert response['redis_cleanup']['total_deleted'] == 4
    assert 'Cleaned up 4 Redis records (2 tasks, 2 cache keys).' in response['message']

    response, service, redis_service = await run(
        result={'status': 'success', 'message': 'Documents deleted successfully'},
        redis_error=RuntimeError('redis unavailable'),
    )
    assert service.calls == 1
    assert redis_service.calls == 1
    assert response['redis_cleanup_error'] == 'redis unavailable'
    assert 'Redis cleanup encountered an error: redis unavailable' in response['message']

    with pytest.raises(HTTPException) as exc_info:
        await run(
            result={'status': 'success', 'message': 'Documents deleted successfully'},
            path_or_url=None,
        )
    assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST

    monkeypatch.setattr(vdb_app, 'require_knowledge_base_edit_permission', _raise_permission_denied)
    with pytest.raises(HTTPException) as exc_info:
        await run(result={'status': 'success', 'message': 'Documents deleted successfully'})
    assert exc_info.value.status_code == HTTPStatus.FORBIDDEN

    monkeypatch.setattr(vdb_app, 'require_knowledge_base_edit_permission', lambda index_name, user_id, tenant_id: None)
    monkeypatch.setattr('database.knowledge_file_lifecycle_db.get_file_record', lambda **kwargs: {'file_id': 'f1'})
    with pytest.raises(HTTPException) as exc_info:
        await run(
            result={'status': 'success', 'message': 'Documents deleted successfully'},
            path_or_url=None,
            file_id='f1',
            scope='source_only',
        )
    assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST
