# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DELETE-PUBLIC-01: public aliases select an existing authorized identity."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from contracts.knowledge_deletion import DELETION_DATASET, KnowledgeDeletionIntent
from contracts.knowledge_ingestion import (
    ACTIVE_LEGACY_FILE_IDS,
    LegacyIngestionSnapshot,
)
from management.services.knowledge_base.deletion_selection import prepare_deletion
from management.services.knowledge_base.source_deletion import SourceDeletion
from nexent.storage.errors import Conflict, ScopeDenied, Unavailable
from nexent.storage.models import StorageScope

from infrastructure.rdb import knowledge_ingestion
from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from infrastructure.rdb.knowledge_deletion import bind_deletion_records
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_deletion_journal import (
    setup as journal_setup,  # noqa: F401
)
from test.backend.services.test_knowledge_ingestion_contract import (
    intent as ingestion_intent,
)


@pytest.fixture
def selection(journal_setup, resources, monkeypatch):  # noqa: F811
    s = journal_setup
    _, update, engine, tables = resources
    value = ingestion_intent(source={'space': 'files', 'key': 'source.txt', 'version': 'etag:v1', 'sha256': 'a' * 64})
    with s.engine.begin() as connection:
        connection.execute(s.table.update().values(bucket_name='bucket', local_source_path='/local/source.txt',
            source_revision='etag:v1', source_upload_sha256='a' * 64, upload_owner_service='management',
            ingestion_request=value.model_dump(mode='json')))
    aliases = knowledge_ingestion.legacy_file_identities.to_metadata(s.table.metadata, schema=None)
    monkeypatch.setattr(knowledge_ingestion, 'legacy_file_identities', aliases)
    aliases.create(s.engine)
    opened = []

    def select(path='source.txt', scope='full', *, file_id=None, user='user-a', tenant='tenant-a'):
        actor = SimpleNamespace(user_id=user, tenant_id=tenant)
        records = bind_deletion_records(
            StorageScope('management', tenant, user, {DELETION_DATASET, ACTIVE_LEGACY_FILE_IDS}), s.engine)
        authorized = bind_cleanse_resources(StorageScope('management', tenant, user, set(tables)), engine)
        opened.extend((records, authorized))
        return prepare_deletion(records, authorized, 'kb-one', path, scope, actor, file_id=file_id, context=context())

    try:
        yield SimpleNamespace(**locals())
    finally:
        for record in opened:
            record.close()


@pytest.mark.parametrize('path', ['source.txt', 's3://bucket/source.txt', '/bucket/source.txt', '/local/source.txt'])
def test_supported_public_aliases_resolve_only_the_stored_source(selection, path):
    s = selection
    row, intent, advance = s.select(path)
    assert row['file_id'] == s.s.intent.file_id and intent.source.key == 'source.txt'
    assert intent.user_id == 'user-a' and advance is True
    assert s.s.row()['deletion_request'] is None


def test_id_is_authoritative_and_unknown_id_never_falls_back_to_path(selection):
    s = selection
    assert s.select('other', file_id=s.s.intent.file_id)[1].file_id == s.s.intent.file_id
    with pytest.raises(ValueError, match='Document not found'):
        s.select(file_id='c' * 32)


@pytest.mark.parametrize('change', [
    {'parent_task_id': 'old-chain'}, {'ingestion_request': None}, {'source_upload_sha256': None},
    {'source_revision': None}, {'source_revision': 'unqualified-legacy-version'},
])
def test_unverified_history_cannot_install_a_deletion_intent(selection, change):
    s = selection
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(**change))
    with pytest.raises(Unavailable):
        s.select()
    assert s.s.row()['deletion_request'] is None


def test_current_read_only_or_revoked_actor_cannot_request_deletion(selection):
    s = selection
    s.update('cleanse_knowledge', created_by='other', ingroup_permission='READ_ONLY')
    with pytest.raises(ScopeDenied):
        s.select()
    s.update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.select()


@pytest.mark.parametrize('status', ['UPLOADING', 'UPLOADED', 'PROCESSING', 'FORWARDING', 'FAILED', 'DELETE_REQUESTED', 'DELETED'])
def test_source_only_keeps_original_completed_requirement(selection, status):
    s = selection
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(status=status))
    with pytest.raises(ValueError, match='Cannot delete source file'):
        s.select(scope='source_only')


def test_other_editor_can_acknowledge_existing_terminal_without_adopting_job_identity(selection):
    s = selection
    row, intent, _ = s.select()
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(status='DELETED', stage='DELETE_DONE', deleted_vector_count=3,
                                                     deletion_request=intent.model_dump(mode='json')))
    s.update('cleanse_memberships', user_id='editor-b')
    s.update('cleanse_accounts', user_id='editor-b')
    s.update('cleanse_group_memberships', user_id='editor-b')
    row, original, advance = s.select(user='editor-b')
    assert row['status'] == 'DELETED' and original.user_id == 'user-a' and advance is False
    assert KnowledgeDeletionIntent.model_validate(s.s.row()['deletion_request']) == intent


def test_other_editor_can_acknowledge_pending_without_executing_as_original_user(selection):
    s = selection
    _, intent, _ = s.select()
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(status='DELETE_REQUESTED', stage='DELETE_RUNTIME_SUBMITTING',
                                                     deletion_request=intent.model_dump(mode='json')))
    s.update('cleanse_memberships', user_id='editor-b')
    s.update('cleanse_accounts', user_id='editor-b')
    s.update('cleanse_group_memberships', user_id='editor-b')
    _, original, advance = s.select(user='editor-b')
    assert original.user_id == 'user-a' and advance is False


def test_source_only_completed_intent_can_be_followed_by_new_full_request(selection):
    s = selection
    _, value, _ = s.select(scope='source_only')
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(stage='SOURCE_DELETED', deletion_request=value.model_dump(mode='json'),
                                                     source_space=None, source_key=None, source_revision=None, source_sha256=None))
    _, intent, advance = s.select(scope='full')
    assert intent.scope == 'full' and intent.source is None and advance


def test_unstarted_no_object_file_can_use_full_deletion(selection):
    s = selection
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(status='UPLOADING', stage='UPLOAD', object_name=None, ingestion_request=None,
            source_space=None, source_key=None, source_revision=None, source_sha256=None, source_upload_sha256=None))
    _, intent, advance = s.select(None, file_id=s.s.intent.file_id)
    assert intent.source is None and intent.object_name is None and advance


def test_foreign_bucket_or_tenant_cannot_select_a_record(selection):
    s = selection
    with pytest.raises(ValueError, match='Document not found'):
        s.select('s3://other/source.txt')
    with pytest.raises(ScopeDenied):
        s.select(tenant='foreign')
    assert s.s.row()['deletion_request'] is None


@pytest.mark.parametrize('scope', ['all', '', None])
def test_invalid_scope_does_not_write_an_intent(selection, scope):
    with pytest.raises(ValueError):
        selection.select(scope=scope)
    assert selection.s.row()['deletion_request'] is None


def test_source_only_without_object_remains_a_client_error(selection):
    s = selection
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(object_name=None))
    with pytest.raises(ValueError, match='A file without a storage object can only use full deletion'):
        s.select(None, scope='source_only', file_id=s.s.intent.file_id)
    assert s.s.row()['deletion_request'] is None



def test_active_legacy_id_and_northbound_path_choose_the_same_deletion_intent(selection):
    s = selection
    original_id = 'legacy-file'
    canonical = s.s.intent.file_id
    with s.s.engine.begin() as conn:
        conn.execute(s.aliases.insert(), {'original_file_id': original_id, 'standard_file_id': canonical,
            'tenant_id': 'tenant-a', 'knowledge_id': 1, 'lifecycle_revision': 3, 'source_generation': 0,
            'plan_sha256': 'd' * 64, 'version': 1, 'created_by': 'user-a', 'updated_by': 'user-a'})
    with pytest.raises(ValueError, match='Invalid file_id'):
        s.select(file_id=original_id)
    with s.s.engine.begin() as conn:
        conn.execute(s.aliases.update().values(activated_at=datetime.now(timezone.utc)))
    _, by_old_id, _ = s.select('ignored', file_id=original_id)
    _, by_path, _ = s.select('s3://bucket/source.txt')
    assert by_old_id == by_path and by_old_id.file_id == canonical
    s.update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.select(file_id=original_id)



@pytest.mark.parametrize("evidence", ["valid", "unversioned", "wrong-hash", "wrong-tenant", "missing-ledger", "wrong-ledger", "deleted-ledger"])
def test_legacy_delete_needs_versioned_source_and_committed_history(selection, mocker, evidence):
    s = selection
    revision = "etag:one" if evidence == "unversioned" else "version:one"
    source = {"space": "files", "key": "source.txt", "version": revision, "sha256": "a" * 64}
    snapshot = LegacyIngestionSnapshot(tenant_id="other" if evidence == "wrong-tenant" else "tenant-a", resource_revision="b" * 64,
        lifecycle_revision=1, legacy_quiesced=True, previous={"status": "COMPLETED", "processing_attempt": 0})
    saved = ingestion_intent(source=source).model_copy(update={"legacy_snapshot": snapshot})
    with s.s.engine.begin() as conn:
        conn.execute(s.s.table.update().values(source_revision=revision, upload_owner_service=None,
            source_upload_sha256="c" * 64 if evidence == "wrong-hash" else None,
            storage_object_id=17, file_size=11, ingestion_request=saved.model_dump(mode="json")))
    ledger = mocker.patch.object(SourceDeletion, "_ledger", return_value={
        "status": "DELETED" if evidence == "deleted-ledger" else "COMMITTED",
    } if evidence != "missing-ledger" else None)
    if evidence == "wrong-ledger":
        ledger.side_effect = Conflict()
    if evidence == "valid":
        row, result, _ = s.select()
        assert result.source == saved.source and result.file_id == row["file_id"]
        ledger.assert_called_once()
    else:
        with pytest.raises(Unavailable):
            s.select()
    if evidence in {"unversioned", "wrong-hash", "wrong-tenant"}:
        ledger.assert_not_called()
    assert s.s.row()["deletion_request"] is None
