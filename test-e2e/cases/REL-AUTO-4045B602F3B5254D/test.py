from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from consts.task_recovery import CONFIG_SERVICE_NAME


@pytest.mark.case_id('REL-AUTO-4045B602F3B5254D')
@pytest.mark.stage('D5')
def test_interrupted_upload_delete_failure_degrades_to_recovery(monkeypatch):
    from database import attachment_db, client as client_db
    from database import knowledge_file_lifecycle_db as lifecycle_db
    from database.db_models import KnowledgeFileLifecycle
    from services.startup_recovery_service import (
        UPLOAD_RECOVERY_GRACE_SECONDS,
        fail_interrupted_uploads,
    )

    file_id = lifecycle_db.new_file_id()
    tenant_id = 'rel-auto-4045-' + file_id[:8]
    index_name = 'idx-' + file_id[:8]
    object_name = 'uploads/' + file_id
    bucket_name = 'nexent-test'

    lifecycle_db.create_file_record(
        file_id=file_id,
        tenant_id=tenant_id,
        knowledge_id=1,
        index_name=index_name,
        original_filename='sample.pdf',
        bucket_name=bucket_name,
        object_name=object_name,
        file_size=1024,
        upload_owner_service=CONFIG_SERVICE_NAME,
        status='UPLOADING',
        stage='UPLOAD',
    )

    old_time = datetime.utcnow() - timedelta(seconds=UPLOAD_RECOVERY_GRACE_SECONDS * 2)
    with client_db.get_db_session() as session:
        session.query(KnowledgeFileLifecycle).filter(
            KnowledgeFileLifecycle.file_id == file_id
        ).update({'create_time': old_time})

    corrections = []
    real_transition = lifecycle_db.transition_file_record

    def spy_transition(fid, **kwargs):
        result = real_transition(fid, **kwargs)
        corrections.append((fid, kwargs))
        return result

    def fake_delete_file(obj, bucket=None):
        return {'success': False, 'error': 'partial object delete failed'}

    def fake_file_exists(obj, bucket=None):
        return True

    monkeypatch.setattr(lifecycle_db, 'transition_file_record', spy_transition)
    monkeypatch.setattr(attachment_db, 'delete_file', fake_delete_file)
    monkeypatch.setattr(client_db.minio_client, 'file_exists', fake_file_exists)

    cutoff = datetime.utcnow() - timedelta(seconds=UPLOAD_RECOVERY_GRACE_SECONDS)

    before = lifecycle_db.list_uploading_files_created_before(
        cutoff, CONFIG_SERVICE_NAME
    )
    assert any(item['file_id'] == file_id for item in before), (
        'fixture record is not selected as an old UPLOADING upload'
    )

    failed = fail_interrupted_uploads(cutoff, CONFIG_SERVICE_NAME)

    try:
        assert failed == 1, 'exactly one record should be failed'

        assert len(corrections) == 2, 'two state transitions are expected'

        _, first = corrections[0]
        assert first['status'] == 'FAILED'
        assert first['stage'] == 'UPLOAD'
        assert first['error_code'] == 'CONTAINER_RESTARTED'
        assert first['error_stage'] == 'UPLOAD'

        _, second = corrections[1]
        assert second['status'] == 'FAILED'
        assert second['stage'] == 'UPLOAD_RECOVERY'
        assert second['error_code'] == 'UPLOAD_RECOVERY_FAILED'
        assert second['error_stage'] == 'UPLOAD_RECOVERY'
        assert 'partial object delete failed' in second['error_message']

        after = lifecycle_db.list_uploading_files_created_before(
            cutoff, CONFIG_SERVICE_NAME
        )
        assert all(item['file_id'] != file_id for item in after), (
            'record must not remain in UPLOADING'
        )

        final = lifecycle_db.get_file_record(file_id=file_id)
        assert final is not None
        assert final['status'] == 'FAILED'
        assert final['stage'] == 'UPLOAD_RECOVERY'
        assert final['error_code'] == 'UPLOAD_RECOVERY_FAILED'
        assert final['error_stage'] == 'UPLOAD_RECOVERY'
        assert 'partial object delete failed' in (final['error_message'] or '')
        assert int(final['version'] or 0) == 2, 'both transitions must commit'
    finally:
        lifecycle_db.delete_file_record(file_id)
