'''D5 reliability test: data-process restart recovery.

Verifies recover_data_process_tasks fails PROCESSING records and already
forwarded FORWARDING records (forward_task_id set) while leaving queued
FORWARDING records (no forward_task_id) and completed UPLOADED records
untouched, and that the associated Celery task markers are cancelled in Redis.
'''

from __future__ import annotations

import uuid

import pytest

from database.client import get_db_session
from database.db_models import KnowledgeFileLifecycle
from database.knowledge_file_lifecycle_db import delete_file_record, get_file_record
from services.redis_service import get_redis_service
from services.startup_recovery_service import recover_data_process_tasks

CASE_ID = 'REL-AUTO-3CE643378A04EF53'
CONTAINER_RESTARTED_MESSAGE = 'Data-process service restarted before the task completed'


def _insert(file_id, tenant_id, knowledge_id, index_name, status, stage, process_task_id, forward_task_id, parent_task_id):
    with get_db_session() as session:
        session.add(
            KnowledgeFileLifecycle(
                file_id=file_id,
                tenant_id=tenant_id,
                knowledge_id=knowledge_id,
                index_name=index_name,
                original_filename=file_id + '.txt',
                status=status,
                stage=stage,
                process_task_id=process_task_id,
                forward_task_id=forward_task_id,
                parent_task_id=parent_task_id,
                delete_flag='N',
            )
        )
        session.flush()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D5')
def test_recover_data_process_tasks_fails_interrupted_and_preserves_queued():
    run = uuid.uuid4().hex
    tenant_id = 'rel-auto-' + run[:12]
    knowledge_id = int(run[:12], 16)
    index_name = 'rel-auto-idx-' + run[:12]

    file_a = uuid.uuid4().hex
    file_b = uuid.uuid4().hex
    file_c = uuid.uuid4().hex
    file_d = uuid.uuid4().hex

    proc_task = 'proc-' + run
    fwd_task = 'fwd-' + run
    parent_task = 'parent-' + run
    unique_task_ids = {proc_task, fwd_task, parent_task}

    redis_service = get_redis_service()
    created_file_ids = [file_a, file_b, file_c, file_d]
    try:
        for task_id in unique_task_ids:
            try:
                redis_service.client.delete('cancel:' + task_id)
            except Exception:
                pass

        _insert(file_a, tenant_id, knowledge_id, index_name, 'PROCESSING', 'PROCESS', proc_task, None, parent_task)
        _insert(file_b, tenant_id, knowledge_id, index_name, 'FORWARDING', 'FORWARD', None, fwd_task, parent_task)
        _insert(file_c, tenant_id, knowledge_id, index_name, 'FORWARDING', 'FORWARD', None, None, None)
        _insert(file_d, tenant_id, knowledge_id, index_name, 'UPLOADED', 'UPLOAD', None, None, None)

        before = {file_id: get_file_record(file_id=file_id) for file_id in created_file_ids}
        for file_id in created_file_ids:
            assert before[file_id] is not None, 'fixture record missing: ' + file_id

        result = recover_data_process_tasks()

        assert result['knowledge_files'] == 2, result
        assert result['cancel_markers'] == len(unique_task_ids), result

        a = get_file_record(file_id=file_a)
        b = get_file_record(file_id=file_b)
        c = get_file_record(file_id=file_c)
        d = get_file_record(file_id=file_d)

        assert a['status'] == 'FAILED'
        assert a['error_code'] == 'CONTAINER_RESTARTED'
        assert a['error_message'] == CONTAINER_RESTARTED_MESSAGE
        assert a['error_stage'] == 'PROCESS'
        assert a['failed_at']
        assert a['version'] == int(before[file_a]['version'] or 0) + 1

        assert b['status'] == 'FAILED'
        assert b['error_code'] == 'CONTAINER_RESTARTED'
        assert b['error_message'] == CONTAINER_RESTARTED_MESSAGE
        assert b['error_stage'] == 'FORWARD'
        assert b['failed_at']
        assert b['version'] == int(before[file_b]['version'] or 0) + 1

        assert c['status'] == 'FORWARDING'
        assert c['forward_task_id'] is None
        assert c['error_code'] is None
        assert c['version'] == int(before[file_c]['version'] or 0)

        assert d['status'] == 'UPLOADED'
        assert d['error_code'] is None
        assert d['version'] == int(before[file_d]['version'] or 0)

        for task_id in unique_task_ids:
            assert redis_service.is_task_cancelled(task_id), 'cancel marker missing: ' + task_id
    finally:
        for file_id in created_file_ids:
            try:
                delete_file_record(file_id)
            except Exception:
                pass
        for task_id in unique_task_ids:
            try:
                redis_service.client.delete('cancel:' + task_id)
            except Exception:
                pass
