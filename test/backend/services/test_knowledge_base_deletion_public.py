# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-KB-PUBLIC-01/02/03: stable public shape and actual principal."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.services.knowledge_base import base_deletion_public as projection
from management.services.knowledge_base import deletion as module
from nexent.storage.errors import Conflict, ScopeDenied


def terminal(**changes):
    row = {'knowledge_id': 1, 'tenant_id': 'tenant', 'index_name': 'kb', 'delete_flag': 'Y',
           'deletion_request': {'knowledge_id': 1, 'index_name': 'kb', 'user_id': 'editor', 'phase': 'deleted'},
           'metadata_cleanup': {'files_deleted': 3, 'source_objects_deleted': 2}}
    return {**row, **changes}


def test_success_keeps_original_response_shape_and_confirmed_counts():
    result = projection.project_base_deletion('kb', terminal())
    assert set(result) == {'status', 'message', 'es_delete_result', 'minio_cleanup', 'redis_cleanup',
                           'lifecycle_cleanup', 'lifecycle_fence_cleanup', 'redis_warnings'}
    assert result['status'] == 'success'
    assert result['minio_cleanup'] == {'total_files_found': 2, 'deleted_count': 2, 'failed_count': 0}
    assert result['redis_cleanup'] == {'index_name': 'kb', 'total_deleted': 0, 'celery_tasks_deleted': 0,
                                       'cache_keys_deleted': 0, 'tasks_cancelled': 0, 'errors': []}
    assert result['redis_warnings'] == []
    assert result['lifecycle_cleanup'] == {'deleted_count': 3}
    assert result['lifecycle_fence_cleanup'] == {'cleared_count': 0, 'failed_count': 0}
    assert result['message'] == 'Index kb deleted successfully. MinIO: 2 files deleted, 0 failed. Redis: Cleaned up 0 records.'
    assert result['es_delete_result'] == {'status': 'success', 'message': 'Index kb and associated files deleted successfully'}


@pytest.mark.parametrize('phase', ['files', 'collection_submitting', 'metadata_pending'])
def test_unfinished_work_uses_existing_blocked_error(phase):
    row = terminal(delete_flag='N')
    row['deletion_request']['phase'] = phase
    with pytest.raises(AppException) as error:
        projection.project_base_deletion('kb', row)
    assert error.value.error_code == ErrorCode.KNOWLEDGE_DELETE_BLOCKED
    assert error.value.details == {'index_name': 'kb', 'blocking_files': []}


@pytest.mark.parametrize('changes', [
    {'index_name': 'foreign'}, {'knowledge_id': 2},
    {'metadata_cleanup': {'files_deleted': -1, 'source_objects_deleted': 1}},
    {'metadata_cleanup': {'files_deleted': True, 'source_objects_deleted': 1}},
    {'metadata_cleanup': {'files_deleted': 0, 'source_objects_deleted': 1}},
    {'metadata_cleanup': {}},
])
def test_mismatched_or_unconfirmed_counts_do_not_project_success(changes):
    with pytest.raises(Conflict):
        projection.project_base_deletion('kb', terminal(**changes))


async def test_facade_passes_actual_user_and_tenant_without_old_clients(monkeypatch):
    request = AsyncMock(return_value=terminal())
    coordinator = SimpleNamespace(request=request)
    root = object()
    monkeypatch.setattr(module, 'default_coordinator', lambda: root)
    monkeypatch.setattr(module, 'default_base_deletion_coordinator', lambda parent: coordinator if parent is root else None)
    result = await module.KnowledgeBaseDocumentDeletionService.delete_knowledge_base('kb', requested_by='editor', tenant_id='tenant')
    assert result['status'] == 'success'
    args, kwargs = request.call_args
    assert args[0] == 'kb' and args[1].user_id == 'editor' and args[1].tenant_id == 'tenant'
    assert kwargs == {}
    request.assert_awaited_once()


async def test_denial_is_propagated_without_false_pending(monkeypatch):
    request = AsyncMock(side_effect=ScopeDenied())
    monkeypatch.setattr(module, 'default_coordinator', lambda: object())
    monkeypatch.setattr(module, 'default_base_deletion_coordinator', lambda _: SimpleNamespace(request=request))
    with pytest.raises(ScopeDenied):
        await module.KnowledgeBaseDocumentDeletionService.delete_knowledge_base('kb', requested_by='editor', tenant_id='tenant')
    request.assert_awaited_once()
