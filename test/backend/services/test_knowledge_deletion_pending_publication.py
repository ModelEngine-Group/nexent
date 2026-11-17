# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DELETE-PUBLISH-01: keep source publication ownership until it is confirmed."""

from datetime import UTC, datetime, timedelta

import pytest
from contracts.agentos_knowledge import KnowledgeJobState, ObjectReference
from contracts.knowledge import STORAGE_LEDGER_DATASET as LEDGER
from contracts.knowledge import STORAGE_LEDGER_HISTORY_DATASET as HISTORY
from contracts.knowledge_deletion import DELETION_DATASET, KnowledgeDeletionIntent
from management.services.knowledge_base.deletion_journal import DeletionJournal
from management.services.knowledge_base.source_deletion import SourceDeletion
from nexent.storage.errors import Conflict, NotFound, OutcomeUnknown, ScopeDenied
from nexent.storage.models import DeleteReceipt, RecordQuery, StorageScope

from infrastructure.rdb.knowledge_deletion import bind_deletion_records
from infrastructure.rdb.source_binding import DATASET as SOURCE
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_deletion_contract import intent
from test.backend.services.test_knowledge_deletion_journal import (
    setup as setup,  # noqa: PLC0414
)
from test.backend.services.test_source_finalize import finalization  # noqa: F401
from test.backend.services.test_source_publish import FILE_ID, publication  # noqa: F401


def publishing(s, *, stage='SOURCE_UPLOAD', bound=False):
    values = {'status': 'UPLOADING', 'stage': stage, 'bucket_name': 'bucket', 'file_size': 11,
              'source_upload_sha256': 'a' * 64, 'upload_owner_service': 'management',
              'source_space': 'files' if bound else None, 'source_key': 'source.txt' if bound else None,
              'source_revision': 'etag:one' if bound else None, 'source_sha256': 'a' * 64 if bound else None}
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values(**values))
    return intent(source=({'space': 'files', 'key': 'source.txt', 'version': 'etag:one', 'sha256': 'a' * 64} if bound else None))


@pytest.mark.parametrize('stage,bound', [('SOURCE_UPLOAD', False), ('SOURCE_CONFIRMED', True), ('SOURCE_ACCOUNTED', True)])
def test_request_preserves_current_publication_phase_and_original_user(setup, stage, bound):
    s = setup
    value = publishing(s, stage=stage, bound=bound)
    row = s.journal.admit(value, s.row(), context=context())
    assert (row['status'], row['stage']) == ('UPLOADING', stage)
    assert s.journal.request(row) == value
    assert row['deletion_request']['user_id'] == 'user-a'
    assert s.journal.admit(value, row, context=context()) == row
    assert s.journal.activate(row, context=context()) == row
    with pytest.raises(Conflict):
        s.journal.begin_runtime(row, context=context())


def test_confirmed_upload_is_bound_once_before_runtime_submission(setup):
    s = setup
    value = publishing(s)
    waiting = s.journal.admit(value, s.row(), context=context())
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values(status='UPLOADED', stage='UPLOAD', source_space='files',
                                                  source_key='source.txt', source_revision='etag:one', source_sha256='a' * 64,
                                                  storage_object_id=17, uploaded_at=datetime(2026, 11, 17, tzinfo=UTC),
                                                  version=waiting['version'] + 1))
    confirmed = s.row()
    row = s.journal.activate(confirmed, context=context())
    assert (row['status'], row['stage']) == ('DELETE_REQUESTED', 'DELETE_ACCEPTED')
    assert row['deletion_request']['source']['version'] == 'etag:one'
    assert row['version'] == confirmed['version'] + 1
    assert row['deletion_request']['user_id'] == 'user-a'
    with pytest.raises(Conflict):
        s.journal.activate(confirmed, context=context())
    _, request = s.journal.begin_runtime(row, context=context())
    assert request == value.runtime_request()


def test_quota_review_with_confirmed_accounted_source_is_deletable(setup):
    s = setup
    value = publishing(s, stage='SOURCE_ACCOUNTED', bound=True)
    waiting = s.journal.admit(value, s.row(), context=context())
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values(stage='SOURCE_REVIEW', error_code='STORAGE_QUOTA_EXCEEDED',
                                                  storage_object_id=17, version=waiting['version'] + 1))
    row = s.journal.activate(s.row(), context=context())
    assert row['status'] == 'DELETE_REQUESTED' and row['stage'] == 'DELETE_ACCEPTED'
    assert row['uploaded_at'] is None


@pytest.mark.parametrize('values', [
    {'stage': 'SOURCE_REVIEW', 'error_code': 'SOURCE_IDENTITY_MISMATCH'},
    {'stage': 'SOURCE_UPLOAD'}, {'stage': 'SOURCE_CONFIRMED'}, {'stage': 'SOURCE_ACCOUNTED'},
])
def test_unconfirmed_publication_stays_waiting_without_advancing_runtime(setup, values):
    s = setup
    value = publishing(s)
    s.journal.admit(value, s.row(), context=context())
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values(**values))
    row = s.row()
    assert s.journal.activate(row, context=context()) == row
    assert s.row()['status'] == 'UPLOADING'


@pytest.mark.parametrize('changed', [{'source_generation': 1}, {'source_key': 'other.txt'}, {'source_sha256': 'b' * 64}])
def test_activation_rejects_changed_generation_or_source_identity(setup, changed):
    s = setup
    value = publishing(s)
    waiting = s.journal.admit(value, s.row(), context=context())
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values({
            'status': 'UPLOADED', 'stage': 'UPLOAD', 'source_space': 'files', 'source_key': 'source.txt',
            'source_revision': 'etag:one', 'source_sha256': 'a' * 64, 'storage_object_id': 17,
            'version': waiting['version'] + 1, **changed,
        }))
    with pytest.raises(Conflict):
        s.journal.activate(s.row(), context=context())


def test_other_actor_cannot_adopt_waiting_request(setup):
    s = setup
    value = publishing(s)
    waiting = s.journal.admit(value, s.row(), context=context())
    with pytest.raises(ScopeDenied):
        DeletionJournal(s.port(user='other')).activate(waiting, context=context())


def test_source_only_cannot_use_publication_waiting_path(setup):
    s = setup
    value = publishing(s, bound=True)
    with pytest.raises(Conflict):
        s.journal.admit(value.model_copy(update={'scope': 'source_only'}), s.row(), context=context())
    assert s.row()['deletion_request'] is None


def test_effective_display_name_is_fixed_when_waiting_publication_is_activated(setup):
    s = setup
    value = publishing(s, bound=True)
    waiting = s.journal.admit(value, s.row(), context=context())
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values(status='UPLOADED', stage='UPLOAD', storage_object_id=17,
                                                  original_filename='source_1.txt', version=waiting['version'] + 1))
    row = s.journal.activate(s.row(), context=context())
    assert row['deletion_request']['filename'] == 'source_1.txt'
    assert s.journal.request(row).filename == 'source_1.txt'


@pytest.mark.parametrize('quota', [None, '0'])
def test_original_finalizer_finishes_with_waiting_intent_then_charge_is_released_once(finalization, quota):  # noqa: F811
    finish, upload, objects, _, configure = finalization
    if quota is not None:
        configure(quota)
    records = bind_deletion_records(StorageScope('management', 'tenant-a', 'user-a', {DELETION_DATASET, LEDGER, HISTORY}), upload._engine)
    try:
        journal = DeletionJournal(records)
        original = journal.record(FILE_ID, context=context())
        source = ObjectReference(space=original['source_space'], key=original['source_key'],
                                 version=original['source_revision'], sha256=original['source_sha256'])
        value = KnowledgeDeletionIntent(knowledge_id=original['knowledge_id'], file_id=FILE_ID, file_version=original['source_generation'],
                                        user_id='user-a', scope='full', index_name=original['index_name'], filename=original['original_filename'],
                                        object_name=original['object_name'], source=source)
        pending = journal.admit(value, original, context=context())
        assert pending['status'] == 'UPLOADING' and pending['stage'] == 'SOURCE_UPLOAD'
        assert finish() == ('uploaded' if quota is None else 'quota_review')
        published = journal.record(FILE_ID, context=context())
        if quota is not None:
            assert published['uploaded_at'] is None
        assert upload.get(SOURCE, FILE_ID, context=context())['source_revision'] == source.version
        row = journal.activate(published, context=context())
        row, _ = journal.begin_runtime(row, context=context())
        row = journal.observe_runtime(row, KnowledgeJobState(**value.runtime_lookup('tenant-a').model_dump(),
                                      status='deleted', physical_cleanup_complete=True), context=context())
        row = journal.confirm_cleanse_drained(row, physical_completion_confirmed=True, context=context())
        objects.scope = StorageScope('management', 'tenant-a', 'user-a', {'files'})
        objects.stat.side_effect = [objects.stat.return_value, NotFound()]
        objects.delete.return_value = DeleteReceipt('deleted', True)
        assert SourceDeletion(records, objects).advance(row, context=context())['status'] == 'DELETED'
        assert records.sum(LEDGER, 'raw_bytes', RecordQuery(), context=context()) == 0
        assert records.get(HISTORY, published['storage_object_id'], context=context())['delete_flag'] == 'Y'
        objects.put.assert_called_once()
        objects.delete.assert_called_once()
    finally:
        records.close()


def test_request_racing_put_keeps_existing_reconciliation_owner_and_never_reuploads(publication):  # noqa: F811
    from management.services.file.source_reconcile import SourceReconciler

    publisher, upload, objects, update = publication
    update(upload_owner_service='nexent-config')
    records = bind_deletion_records(StorageScope('management', 'tenant-a', 'user-a', {DELETION_DATASET}), upload._engine)
    journal = DeletionJournal(records)
    put = objects.put.side_effect

    def finish_put(*args, **kwargs):
        metadata = put(*args, **kwargs)
        row = journal.record(FILE_ID, context=context())
        value = KnowledgeDeletionIntent(knowledge_id=row['knowledge_id'], file_id=FILE_ID, file_version=0,
                                        user_id='user-a', scope='full', index_name=row['index_name'],
                                        filename=row['original_filename'], object_name=row['object_name'])
        journal.admit(value, row, context=context())
        return metadata

    objects.put.side_effect = finish_put
    try:
        with pytest.raises(OutcomeUnknown):
            publisher.publish(FILE_ID, b'source', content_type='text/plain', expected_version=0, context=context())
        pending = journal.record(FILE_ID, context=context())
        assert pending['stage'] == 'SOURCE_UPLOAD' and pending['source_revision'] is None
        now = datetime.now(UTC) + timedelta(seconds=301)
        assert SourceReconciler(upload, objects, clock=lambda: now).reconcile(
            FILE_ID, owner_service='nexent-config', owner_user_id='user-a', expected_version=pending['version'],
            cutoff=now - timedelta(seconds=300), context=context()) == 'confirmed'
        row = journal.record(FILE_ID, context=context())
        assert row['stage'] == 'SOURCE_CONFIRMED' and row['source_revision'] == 'etag:v1'
        assert journal.request(row).source is None
        assert journal.activate(row, context=context()) == row
        objects.put.assert_called_once()
        objects.delete.assert_not_called()
    finally:
        records.close()
