# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DELETE-PUBLIC-02: confirmed results preserve the public deletion fields."""

import pytest
from management.services.knowledge_base.deletion_public import (
    project_deletion,
    with_cleanup_summary,
)
from nexent.storage.errors import Conflict

from test.backend.services.test_knowledge_deletion_contract import intent


def row(scope='full', **changes):
    return {'deletion_request': intent(scope=scope).model_dump(mode='json'), 'status': 'DELETED',
            'stage': 'DELETE_DONE', 'deleted_vector_count': 3, **changes}


def test_full_uses_actual_confirmed_count_and_hides_internal_identity():
    result = project_deletion(row())
    assert result['status'] == 'success' and result['deleted_es_count'] == 3
    assert result['deleted_minio'] and result['lifecycle_deleted'] and not result['source_available']
    assert not {'deletion_request', 'user_id', 'tenant_id'} & result.keys()


def test_source_only_retains_identity_and_vectors():
    result = project_deletion(row('source_only', status='COMPLETED', stage='SOURCE_DELETED'))
    assert result['deleted_es_count'] == 0 and not result['lifecycle_deleted']
    assert result['message'] == 'Source file deleted; index chunks and vectors preserved.'


def test_no_object_response_remains_explicit():
    value = intent(source=None, object_name=None).model_dump(mode='json')
    result = project_deletion(row(deletion_request=value, deleted_vector_count=0))
    assert result['lifecycle_deleted'] and not result['deleted_minio']
    assert result['message'] == 'Lifecycle record deleted; no storage object was created.'


def test_unknown_terminal_count_is_never_a_success():
    with pytest.raises(Conflict):
        project_deletion(row(deleted_vector_count=None))


@pytest.mark.parametrize('status,stage', [('UPLOADING', 'SOURCE_UPLOAD'), ('DELETE_REQUESTED', 'DELETE_ACCEPTED'),
                                          ('DELETE_REQUESTED', 'DELETE_RUNTIME_PENDING')])
def test_pending_does_not_invent_counts_or_completion(status, stage):
    result = project_deletion(row(status=status, stage=stage, deleted_vector_count=None))
    assert result['deletion_pending'] and result['source_available']
    assert 'deleted_es_count' not in result and 'lifecycle_deleted' not in result


def test_summary_preserves_existing_fields_without_mutating_the_input():
    original = project_deletion(row())
    result = with_cleanup_summary(original)
    assert 'redis_cleanup' not in original
    assert result['redis_cleanup'] == {'total_deleted': 0, 'celery_tasks_deleted': 0, 'cache_keys_deleted': 0, 'errors': []}
    assert result['message'] == 'Documents deleted successfully. Cleaned up 0 Redis records (0 tasks, 0 cache keys).'
