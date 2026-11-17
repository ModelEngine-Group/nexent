# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Project persistent deletion outcomes into the existing public response."""

from contracts.knowledge_deletion import KnowledgeDeletionIntent
from nexent.storage.errors import Conflict


def project_deletion(row):
    intent = KnowledgeDeletionIntent.model_validate(row['deletion_request'])
    full = intent.scope == 'full'
    task_ids = sorted({row[name] for name in ('process_task_id', 'forward_task_id') if row.get(name)})
    cancellation = {'task_ids': task_ids, 'cancelled_count': len(task_ids)}
    complete = (row['status'] == 'DELETED' and row['stage'] == 'DELETE_DONE') if full else (
        row['status'] == 'COMPLETED' and row['stage'] == 'SOURCE_DELETED'
    )
    if not complete:
        return {
            'status': 'pending', 'scope': intent.scope, 'deletion_pending': True,
            'lifecycle_status': 'DELETE_REQUESTED' if full else 'COMPLETED',
            'source_available': bool(intent.object_name),
            'message': 'Deletion requested; waiting for physical cleanup.',
            'cancelled_tasks': cancellation,
        }
    count = row['deleted_vector_count'] if full else 0
    if count is None:
        raise Conflict()
    result = {
        'status': 'success', 'scope': intent.scope, 'deleted_es_count': count,
        'deleted_minio': bool(intent.object_name), 'source_available': False, 'lifecycle_deleted': full,
    }
    if not full:
        result['message'] = 'Source file deleted; index chunks and vectors preserved.'
    elif intent.object_name is None:
        result['message'] = 'Lifecycle record deleted; no storage object was created.'
    result['cancelled_tasks'] = cancellation
    return result


def with_cleanup_summary(result):
    """New jobs produce no Celery cache records; retain the public summary shape."""
    result = dict(result)
    result['redis_cleanup'] = {
        'total_deleted': 0, 'celery_tasks_deleted': 0, 'cache_keys_deleted': 0, 'errors': [],
    }
    message = result.get('message', 'Documents deleted successfully')
    result['message'] = f'{message}. Cleaned up 0 Redis records (0 tasks, 0 cache keys).'
    return result
