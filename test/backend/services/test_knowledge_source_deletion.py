# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DELETE-SOURCE-01/02: exact source deletion precedes atomic charge release."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.knowledge import STORAGE_LEDGER_DATASET as LEDGER
from contracts.knowledge import STORAGE_LEDGER_HISTORY_DATASET as HISTORY
from contracts.knowledge_deletion import DELETION_DATASET, DELETION_KNOWLEDGE_DATASET
from management.services.knowledge_base.deletion_journal import DeletionJournal
from management.services.knowledge_base.source_deletion import SourceDeletion
from nexent.storage.errors import Conflict, NotFound, OutcomeUnknown, ScopeDenied
from nexent.storage.models import (
    DeleteReceipt,
    ObjectMetadata,
    ObjectRef,
    Revision,
    StorageScope,
    WriteOutcome,
)

from infrastructure.rdb import knowledge_deletion as module
from infrastructure.rdb.storage_ledger import ledger_catalog
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_deletion_contract import intent
from test.backend.services.test_knowledge_deletion_journal import (
    setup as journal_setup,  # noqa: F401
)


@pytest.fixture
def setup(journal_setup, monkeypatch):  # noqa: F811
    s = journal_setup
    definition, original, audit = ledger_catalog()
    ledger = sa.Table('deletion_ledger', sa.MetaData(), *[
        sa.Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable) for c in original.c
    ])
    ledger.create(s.engine)
    monkeypatch.setattr(module, 'ledger_catalog', lambda: (definition, ledger, audit))
    knowledge_definition, original_knowledge, knowledge_audit = module.metadata_catalog()
    knowledge = sa.Table('deletion_knowledge', sa.MetaData(), *[
        sa.Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable) for c in original_knowledge.c
    ])
    knowledge.create(s.engine)
    monkeypatch.setattr(module, 'metadata_catalog', lambda: (knowledge_definition, knowledge, knowledge_audit))
    value = intent(source={'space': 'files', 'key': 'source.txt', 'version': 'etag:one', 'sha256': 'a' * 64})
    with s.engine.begin() as c:
        c.execute(knowledge.insert(), {'knowledge_id': 1, 'tenant_id': 'tenant-a', 'index_name': 'kb-one',
                                      'last_doc_update_time': datetime(2026, 1, 1, tzinfo=UTC), 'delete_flag': 'N', 'created_by': 'uploader-a', 'version': 0})
        c.execute(s.table.update().values(file_size=11, bucket_name='bucket', storage_object_id=17,
                                         source_revision=value.source.version, source_upload_sha256=value.source.sha256,
                                         upload_owner_service='management', uploaded_at=datetime(2026, 11, 17, tzinfo=UTC)))
        c.execute(ledger.insert(), {'storage_object_id': 17, 'tenant_id': 'tenant-a', 'knowledge_id': 1,
                                   'index_name': 'kb-one', 'bucket_name': 'bucket', 'object_name': 'source.txt',
                                   'raw_bytes': 11, 'status': 'COMMITTED', 'version': 0, 'delete_flag': 'N',
                                   'create_time': datetime(2026, 11, 17, tzinfo=UTC), 'update_time': datetime(2026, 11, 17, tzinfo=UTC)})
    records = module.bind_deletion_records(StorageScope('management', 'tenant-a', 'user-a', {DELETION_DATASET, DELETION_KNOWLEDGE_DATASET, LEDGER, HISTORY}), s.engine)
    journal = DeletionJournal(records)
    admitted = journal.admit(value, journal.record(value.file_id, context=context()), context=context())
    with s.engine.begin() as c:
        c.execute(s.table.update().values(stage='DELETE_SOURCE_PENDING', deleted_vector_count=0))
    row = lambda: journal.record(value.file_id, context=context())
    target = ObjectRef('files', 'source.txt', Revision(value.source.version))
    metadata = ObjectMetadata(target, 11, 'text/plain', 'one', value.source.sha256)
    objects = Mock(scope=StorageScope('management', 'tenant-a', 'user-a', {'files'}))
    objects.stat.side_effect = [metadata, NotFound()]
    objects.delete.return_value = DeleteReceipt('deleted', True)
    deletion = SourceDeletion(records, objects)
    try:
        yield SimpleNamespace(**locals())
    finally:
        records.close()


def test_closed_unversioned_source_is_deleted_once_before_charge_and_final_state(setup):
    s = setup
    done = s.deletion.advance(s.row(), context=context())
    assert done['status'] == 'DELETED'
    assert s.objects.delete.call_count == 1
    assert s.objects.delete.call_args.args == (ObjectRef('files', 'source.txt'),)
    ledger = s.records.get(HISTORY, 17, context=context())
    assert ledger['status'] == 'DELETED' and ledger['delete_flag'] == 'Y'
    assert ledger['updated_by'] == 'user-a'


def test_immutable_version_is_targeted_without_touching_other_keys(setup):
    s = setup
    value = intent(source={'space': 'files', 'key': 'source.txt', 'version': 'version:one', 'sha256': 'a' * 64})
    with s.s.engine.begin() as c:
        c.execute(s.s.table.update().values(source_revision=value.source.version, deletion_request=value.model_dump(mode='json')))
    target = ObjectRef('files', 'source.txt', Revision(value.source.version))
    s.objects.stat.side_effect = [ObjectMetadata(target, 11, 'text/plain', 'one', value.source.sha256), NotFound()]
    s.deletion.advance(s.row(), context=context())
    assert s.objects.delete.call_count == 1 and s.objects.delete.call_args.args == (target,)


def test_unknown_delete_is_only_probed_and_never_replayed(setup):
    s = setup
    s.objects.delete.side_effect = OutcomeUnknown()
    with pytest.raises(OutcomeUnknown):
        s.deletion.advance(s.row(), context=context())
    assert s.row()['stage'] == 'DELETE_SOURCE_DELETING'
    assert s.records.get(HISTORY, 17, context=context())['status'] == 'COMMITTED'
    s.objects.stat.side_effect = [s.metadata, NotFound()]
    pending = s.deletion.advance(s.row(), context=context())
    assert pending['stage'] == 'DELETE_SOURCE_DELETING'
    assert s.deletion.advance(s.row(), context=context())['status'] == 'DELETED'
    assert s.objects.delete.call_count == 1


@pytest.mark.parametrize('change', ['revision', 'hash', 'size', 'legacy'])
def test_changed_or_unproven_source_does_not_delete_or_release(setup, change):
    s = setup
    if change == 'legacy':
        with s.s.engine.begin() as c:
            c.execute(s.s.table.update().values(source_upload_sha256=None))
    else:
        s.objects.stat.side_effect = None
        s.objects.stat.return_value = ObjectMetadata(
            ObjectRef('files', 'source.txt', Revision('etag:other' if change == 'revision' else 'etag:one')),
            12 if change == 'size' else 11, 'text/plain', 'one', 'b' * 64 if change == 'hash' else 'a' * 64)
    with pytest.raises((Conflict, OutcomeUnknown)):
        s.deletion.advance(s.row(), context=context())
    s.objects.delete.assert_not_called()
    assert s.records.get(HISTORY, 17, context=context())['status'] == 'COMMITTED'


def test_ledger_mismatch_rolls_back_terminal_state_and_keeps_charge(setup):
    s = setup
    with s.s.engine.begin() as c:
        c.execute(s.ledger.update().values(raw_bytes=99))
    with pytest.raises(Conflict):
        s.deletion.advance(s.row(), context=context())
    assert s.row()['stage'] == 'DELETE_SOURCE_PENDING'
    s.objects.delete.assert_not_called()
    assert s.records.get(HISTORY, 17, context=context())['status'] == 'COMMITTED'


def test_unknown_object_receipt_cannot_release_charge(setup):
    s = setup
    s.objects.delete.return_value = DeleteReceipt('unknown', False, WriteOutcome.UNKNOWN)
    with pytest.raises(OutcomeUnknown):
        s.deletion.advance(s.row(), context=context())
    assert s.records.get(HISTORY, 17, context=context())['status'] == 'COMMITTED'


def test_no_object_is_verified_without_sending_a_delete(setup):
    s = setup
    s.objects.stat.side_effect = NotFound()
    assert s.deletion.advance(s.row(), context=context())['status'] == 'DELETED'
    s.objects.delete.assert_not_called()


def test_source_only_finishes_without_removing_file_identity(setup):
    s = setup
    value = s.value.model_copy(update={'scope': 'source_only'})
    with s.s.engine.begin() as c:
        c.execute(s.s.table.update().values(status='COMPLETED', stage='DELETE_ACCEPTED', deletion_request=value.model_dump(mode='json')))
    done = s.deletion.advance(s.row(), context=context())
    assert done['status'] == 'COMPLETED' and done['stage'] == 'SOURCE_DELETED'
    assert done['source_key'] is None and done['object_name'] == 'source.txt'


def test_other_actor_object_handle_cannot_be_used(setup):
    s = setup
    s.objects.scope = StorageScope('management', 'tenant-a', 'other', {'files'})
    with pytest.raises(ScopeDenied):
        SourceDeletion(s.records, s.objects)


def test_terminal_failure_rolls_back_both_ledger_status_and_soft_delete(setup, monkeypatch):
    s = setup
    finish = DeletionJournal.finish_source
    monkeypatch.setattr(DeletionJournal, 'finish_source', Mock(side_effect=Conflict()))
    with pytest.raises(Conflict):
        s.deletion.advance(s.row(), context=context())
    assert s.row()['stage'] == 'DELETE_SOURCE_DELETING'
    ledger = s.records.get(HISTORY, 17, context=context())
    assert (ledger['status'], ledger['delete_flag'], ledger['version']) == ('COMMITTED', 'N', 0)
    monkeypatch.setattr(DeletionJournal, 'finish_source', finish)
    s.objects.stat.side_effect = NotFound()
    assert s.deletion.advance(s.row(), context=context())['status'] == 'DELETED'
    assert s.objects.delete.call_count == 1


def test_full_delete_after_source_only_reuses_released_history_without_double_charge(setup):
    s = setup
    source = s.value.model_copy(update={'scope': 'source_only'})
    with s.s.engine.begin() as c:
        c.execute(s.s.table.update().values(status='COMPLETED', stage='DELETE_ACCEPTED', deletion_request=source.model_dump(mode='json')))
    done = s.deletion.advance(s.row(), context=context())
    full = s.value.model_copy(update={'source': None})
    s.journal.admit(full, done, context=context())
    with s.s.engine.begin() as c:
        c.execute(s.s.table.update().values(stage='DELETE_SOURCE_PENDING', deleted_vector_count=0))
    s.objects.stat.side_effect = NotFound()
    revision = s.records.get(HISTORY, 17, context=context())['version']
    assert s.deletion.advance(s.row(), context=context())['status'] == 'DELETED'
    assert s.records.get(HISTORY, 17, context=context())['version'] == revision
    assert s.objects.delete.call_count == 1


def test_missing_pointer_does_not_allow_deleting_an_existing_object(setup):
    s = setup
    with s.s.engine.begin() as c:
        c.execute(s.s.table.update().values(source_space=None, source_key=None, source_revision=None, source_sha256=None,
                                           deletion_request=s.value.model_copy(update={'source': None}).model_dump(mode='json')))
    with pytest.raises(Conflict):
        s.deletion.advance(s.row(), context=context())
    s.objects.delete.assert_not_called()


def test_unstarted_upload_without_any_object_or_charge_can_finish(setup):
    s = setup
    value = s.value.model_copy(update={'source': None, 'object_name': None})
    with s.s.engine.begin() as c:
        c.execute(s.s.table.update().values(object_name=None, storage_object_id=None, source_space=None, source_key=None,
                                           source_revision=None, source_sha256=None, deletion_request=value.model_dump(mode='json')))
    assert SourceDeletion(s.records, None).advance(s.row(), context=context())['status'] == 'DELETED'
    s.objects.delete.assert_not_called()
