'''D5 reliability: interrupted-upload recovery must stay scoped to the restarting service.'''

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import inspect as schema_inspect

from consts.task_recovery import CONFIG_SERVICE_NAME, NORTHBOUND_SERVICE_NAME
from database.client import db_client, get_db_session, minio_client
from database.db_models import KnowledgeFileLifecycle
from database.knowledge_file_lifecycle_db import (
    create_file_record,
    delete_file_record,
    get_file_record,
    list_uploading_files_created_before,
)
from services.startup_recovery_service import fail_interrupted_uploads


def _set_create_time(file_id: str, create_time: datetime) -> None:
    with get_db_session() as session:
        session.query(KnowledgeFileLifecycle).filter(
            KnowledgeFileLifecycle.file_id == file_id
        ).update(
            {KnowledgeFileLifecycle.create_time: create_time},
            synchronize_session=False,
        )


@pytest.mark.case_id('REL-AUTO-4CBD1BF08020ABF9')
@pytest.mark.stage('D5')
def test_interrupted_upload_recovery_ownership_isolation() -> None:
    schema = KnowledgeFileLifecycle.__table__.schema
    table = KnowledgeFileLifecycle.__tablename__
    inspector = schema_inspect(db_client.engine)
    columns = {c['name'] for c in inspector.get_columns(table, schema=schema)}
    assert 'upload_owner_service' in columns
    indexes = {i['name'] for i in inspector.get_indexes(table, schema=schema)}
    assert 'idx_knowledge_file_lifecycle_upload_recovery' in indexes

    run_id = uuid.uuid4().hex
    tenant_id = 'rel-auto-' + run_id
    index_name = 'rel_auto_recovery_idx_' + run_id
    knowledge_id = -int(run_id[:12], 16)
    bucket = minio_client.default_bucket
    object_a = 'rel_auto_upload_recovery/' + run_id + '/a.bin'
    object_b = 'rel_auto_upload_recovery/' + run_id + '/b.bin'
    file_a = uuid.uuid4().hex
    file_b = uuid.uuid4().hex
    file_c = uuid.uuid4().hex
    file_d = uuid.uuid4().hex

    cutoff = datetime.utcnow()
    expired = cutoff - timedelta(hours=1)
    within_grace = cutoff + timedelta(minutes=5)

    def create(file_id, owner, object_name, original_filename):
        return create_file_record(
            file_id=file_id,
            tenant_id=tenant_id,
            knowledge_id=knowledge_id,
            index_name=index_name,
            original_filename=original_filename,
            bucket_name=bucket,
            object_name=object_name,
            upload_owner_service=owner,
            status='UPLOADING',
            stage='UPLOAD',
        )

    try:
        create(file_a, CONFIG_SERVICE_NAME, object_a, 'recovery-a.bin')
        create(file_b, NORTHBOUND_SERVICE_NAME, object_b, 'recovery-b.bin')
        create(file_c, None, None, 'recovery-c.bin')
        create(file_d, CONFIG_SERVICE_NAME, None, 'recovery-d.bin')

        _set_create_time(file_a, expired)
        _set_create_time(file_b, expired)
        _set_create_time(file_c, expired)
        _set_create_time(file_d, within_grace)

        for object_name in (object_a, object_b):
            ok, _ = minio_client.upload_fileobj(io.BytesIO(b'rel-auto-test'), object_name, bucket)
            assert ok, 'failed to upload test object ' + object_name
        assert minio_client.file_exists(object_a, bucket)
        assert minio_client.file_exists(object_b, bucket)

        boundary = list_uploading_files_created_before(cutoff, CONFIG_SERVICE_NAME)
        boundary_ids = {record['file_id'] for record in boundary}
        assert file_a in boundary_ids
        assert file_b not in boundary_ids
        assert file_c not in boundary_ids
        assert file_d not in boundary_ids

        with pytest.raises(ValueError):
            list_uploading_files_created_before(cutoff, '')

        fail_interrupted_uploads(cutoff, CONFIG_SERVICE_NAME)

        record_a = get_file_record(file_id=file_a)
        record_b = get_file_record(file_id=file_b)
        record_c = get_file_record(file_id=file_c)
        record_d = get_file_record(file_id=file_d)

        assert record_a['status'] == 'FAILED'
        assert record_a['error_code'] == 'CONTAINER_RESTARTED'
        assert record_a['stage'] == 'UPLOAD'
        assert record_a['version'] == 1
        assert not minio_client.file_exists(object_a, bucket)

        assert record_b['status'] == 'UPLOADING'
        assert not record_b['error_code']
        assert record_b['version'] == 0
        assert minio_client.file_exists(object_b, bucket)

        assert record_c['status'] == 'UPLOADING'
        assert record_c['version'] == 0

        assert record_d['status'] == 'UPLOADING'
        assert record_d['version'] == 0
    finally:
        for object_name in (object_a, object_b):
            try:
                if minio_client.file_exists(object_name, bucket):
                    minio_client.delete_file(object_name, bucket)
            except Exception:
                pass
        for file_id in (file_a, file_b, file_c, file_d):
            try:
                delete_file_record(file_id)
            except Exception:
                pass
