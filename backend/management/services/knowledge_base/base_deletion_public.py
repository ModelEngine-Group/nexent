# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Keep the public KB deletion contract over confirmed persistent cleanup."""

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.knowledge_admission import KnowledgeBaseDeletionIntent
from nexent.storage.errors import Conflict


def project_base_deletion(index_name, row):
    intent = KnowledgeBaseDeletionIntent.model_validate(row['deletion_request'])
    if intent.index_name != index_name or row['index_name'] != index_name or intent.knowledge_id != row['knowledge_id']:
        raise Conflict()
    if row['delete_flag'] == 'N' and intent.phase != 'deleted':
        raise AppException(ErrorCode.KNOWLEDGE_DELETE_BLOCKED,
                           details={'index_name': index_name, 'blocking_files': []})
    if row['delete_flag'] != 'Y' or intent.phase != 'deleted':
        raise Conflict()
    counts = row['metadata_cleanup']
    files, sources = counts.get('files_deleted'), counts.get('source_objects_deleted')
    if type(files) is not int or type(sources) is not int or not 0 <= sources <= files:
        raise Conflict()
    return {
        'status': 'success',
        'message': (f'Index {index_name} deleted successfully. MinIO: {sources} files deleted, '
                    '0 failed. Redis: Cleaned up 0 records.'),
        'es_delete_result': {'status': 'success', 'message': f'Index {index_name} and associated files deleted successfully'},
        'minio_cleanup': {'total_files_found': sources, 'deleted_count': sources, 'failed_count': 0},
        'redis_cleanup': {'index_name': index_name, 'total_deleted': 0, 'celery_tasks_deleted': 0,
                          'cache_keys_deleted': 0, 'tasks_cancelled': 0, 'errors': []},
        'redis_warnings': [],
        'lifecycle_cleanup': {'deleted_count': files},
        'lifecycle_fence_cleanup': {'cleared_count': 0, 'failed_count': 0},
    }
