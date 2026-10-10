from __future__ import annotations

import asyncio
import io
import os
import uuid
from datetime import datetime, timedelta

import pytest

from shared.config import load_secret_env

try:
    _secret_env = load_secret_env()
except Exception:
    _secret_env = {}
for _key, _value in _secret_env.items():
    os.environ.setdefault(_key, _value)

from consts.task_recovery import CONFIG_SERVICE_NAME
from database.client import get_db_session, minio_client
from database.db_models import KnowledgeFileLifecycle
from database.knowledge_file_lifecycle_db import (
    create_file_record,
    delete_file_record,
    get_file_record,
    list_uploading_files_created_before,
)
from services import startup_recovery_service

GRACE_SECONDS = startup_recovery_service.UPLOAD_RECOVERY_GRACE_SECONDS
OTHER_SERVICE_NAME = 'nexent-other-service'


def _backdate_create_time(file_id, create_time):
    with get_db_session() as session:
        row = (
            session.query(KnowledgeFileLifecycle)
            .filter(KnowledgeFileLifecycle.file_id == file_id)
            .one()
        )
        row.create_time = create_time


def _write_object(object_name, bucket, content=b'partial upload for recovery test'):
    success, result = minio_client.upload_fileobj(io.BytesIO(content), object_name, bucket)
    assert success, 'failed to write test object %r: %s' % (object_name, result)


def _create_record(owner, age_seconds, bucket, object_name, tenant_id, index_name, knowledge_id):
    file_id = uuid.uuid4().hex
    create_file_record(
        file_id=file_id,
        tenant_id=tenant_id,
        knowledge_id=knowledge_id,
        index_name=index_name,
        original_filename='interrupted-upload.bin',
        bucket_name=bucket,
        object_name=object_name,
        upload_owner_service=owner,
        status='UPLOADING',
        stage='UPLOAD',
    )
    _backdate_create_time(file_id, datetime.utcnow() - timedelta(seconds=age_seconds))
    return file_id


@pytest.mark.asyncio
@pytest.mark.case_id('REL-AUTO-D78B50240E78970B')
@pytest.mark.stage('D5')
async def test_interrupted_upload_startup_recovery(monkeypatch):
    GRACE_SECONDS = startup_recovery_service.UPLOAD_RECOVERY_GRACE_SECONDS
    assert GRACE_SECONDS == 30 * 60
    now = datetime.utcnow()
    immediate_cutoff = now - timedelta(seconds=GRACE_SECONDS)
    bucket = minio_client.default_bucket
    tenant_id = 'd5-recovery-%s' % uuid.uuid4().hex[:12]
    index_name = 'd5_recovery_idx_%s' % uuid.uuid4().hex[:12]
    knowledge_id = 1000000 + int(uuid.uuid4().hex[:6], 16)

    file_ids = []
    object_names = {}
    real_file_exists = minio_client.file_exists

    def cleanup():
        for file_id in file_ids:
            try:
                delete_file_record(file_id)
            except Exception:
                pass
        for object_name in object_names.values():
            try:
                if real_file_exists(object_name, bucket):
                    minio_client.delete_file(object_name, bucket)
            except Exception:
                pass

    try:
        object_a = 'd5-recovery/%s.bin' % uuid.uuid4().hex
        file_a = _create_record(
            owner=CONFIG_SERVICE_NAME,
            age_seconds=GRACE_SECONDS + 900,
            bucket=bucket,
            object_name=object_a,
            tenant_id=tenant_id,
            index_name=index_name,
            knowledge_id=knowledge_id,
        )
        _write_object(object_a, bucket)
        file_ids.append(file_a)
        object_names[file_a] = object_a

        file_b = _create_record(
            owner=CONFIG_SERVICE_NAME,
            age_seconds=600,
            bucket=bucket,
            object_name=None,
            tenant_id=tenant_id,
            index_name=index_name,
            knowledge_id=knowledge_id,
        )
        file_ids.append(file_b)

        file_c = _create_record(
            owner=OTHER_SERVICE_NAME,
            age_seconds=GRACE_SECONDS + 900,
            bucket=bucket,
            object_name=None,
            tenant_id=tenant_id,
            index_name=index_name,
            knowledge_id=knowledge_id,
        )
        file_ids.append(file_c)

        before_a = get_file_record(file_id=file_a)
        assert before_a is not None
        assert before_a['status'] == 'UPLOADING'

        tasks_before = set(startup_recovery_service._upload_cleanup_tasks)
        await startup_recovery_service.schedule_interrupted_upload_cleanup(CONFIG_SERVICE_NAME)
        delayed_tasks = startup_recovery_service._upload_cleanup_tasks - tasks_before
        for task in delayed_tasks:
            task.cancel()
        if delayed_tasks:
            await asyncio.gather(*delayed_tasks, return_exceptions=True)

        after_a = get_file_record(file_id=file_a)
        assert after_a is not None
        assert after_a['status'] == 'FAILED'
        assert after_a['stage'] == 'UPLOAD'
        assert after_a['error_code'] == 'CONTAINER_RESTARTED'
        assert after_a['failed_at']
        assert after_a['version'] == before_a['version'] + 1

        assert real_file_exists(object_a, bucket) is False

        after_b = get_file_record(file_id=file_b)
        assert after_b is not None and after_b['status'] == 'UPLOADING'
        after_c = get_file_record(file_id=file_c)
        assert after_c is not None and after_c['status'] == 'UPLOADING'

        delayed_count = startup_recovery_service.fail_interrupted_uploads(now, CONFIG_SERVICE_NAME)
        assert delayed_count == 1
        assert get_file_record(file_id=file_b)['status'] == 'FAILED'
        assert get_file_record(file_id=file_c)['status'] == 'UPLOADING'

        object_d = 'd5-recovery/%s.bin' % uuid.uuid4().hex
        file_d = _create_record(
            owner=CONFIG_SERVICE_NAME,
            age_seconds=GRACE_SECONDS + 900,
            bucket=bucket,
            object_name=object_d,
            tenant_id=tenant_id,
            index_name=index_name,
            knowledge_id=knowledge_id,
        )
        _write_object(object_d, bucket)
        file_ids.append(file_d)
        object_names[file_d] = object_d

        import database.attachment_db as attachment_db

        def _fail_delete(object_name, bucket=None):
            return {'success': False, 'object_name': object_name, 'error': 'simulated delete failure'}

        monkeypatch.setattr(attachment_db, 'delete_file', _fail_delete)
        monkeypatch.setattr(minio_client, 'file_exists', lambda object_name, bucket=None: True)

        recovery_count = startup_recovery_service.fail_interrupted_uploads(immediate_cutoff, CONFIG_SERVICE_NAME)
        assert recovery_count == 1

        after_d = get_file_record(file_id=file_d)
        assert after_d is not None
        assert after_d['status'] == 'FAILED'
        assert after_d['stage'] == 'UPLOAD_RECOVERY'
        assert after_d['error_code'] == 'UPLOAD_RECOVERY_FAILED'
        assert real_file_exists(object_d, bucket) is True

        with pytest.raises(ValueError):
            list_uploading_files_created_before(now, '')
    finally:
        cleanup()
