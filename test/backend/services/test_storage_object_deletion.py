# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SOURCE-OBJECT-01/02 proves source ownership and release with actual scoped SI."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.knowledge import KnowledgeStorageContext
from nexent.storage.errors import Conflict, OutcomeUnknown, Unavailable
from nexent.storage.models import DeleteReceipt, StorageScope, WriteOutcome

from infrastructure.rdb.storage_ledger import (
    HISTORY,
    LEDGER,
    bind_ledger_records,
    ledger_catalog,
)
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_file_reader import reader  # noqa: F401


@pytest.fixture
def deletion(reader, mocker):  # noqa: F811
    from management.services.file import object_deletion as module

    r = reader
    engine = r.actor_engine
    engine.update_execution_options(schema_translate_map={'nexent': None})
    _, table, _ = ledger_catalog()
    table.create(engine)
    with engine.begin() as conn:
        conn.execute(table.insert(), {'storage_object_id': 1, 'tenant_id': 'tenant-a', 'knowledge_id': 1,
            'index_name': 'kb-one', 'bucket_name': 'owned', 'object_name': 'knowledge_base/one', 'raw_bytes': 10,
            'status': 'COMMITTED', 'version': 1, 'created_by': 'user-a', 'delete_flag': 'N'})
    mocker.patch.object(module.environment, 'MINIO_DEFAULT_BUCKET', 'owned')
    mocker.patch('management.services.knowledge_base.source_reference.MINIO_DEFAULT_BUCKET', 'owned')
    opened, events, closed = [], [], []

    @contextmanager
    def ledger_ports(tenant, actor, *, context):
        assert (tenant, actor) == ('tenant-a', r.actor.user_id)
        opened.append((tenant, actor))
        records = bind_ledger_records(StorageScope('management', tenant, actor, {LEDGER, HISTORY}), engine)
        try:
            yield records
        finally:
            records.close()

    objects = SimpleNamespace(scope=StorageScope('management', r.actor.tenant_id, r.actor.user_id, {'files'}))

    def remove(ref, *, context):
        with engine.connect() as conn:
            assert conn.execute(table.select()).mappings().first()['status'] == 'COMMITTED'
        events.append(ref.key)
        return DeleteReceipt(context.operation_id, True)

    objects.delete = Mock(side_effect=remove)

    @contextmanager
    def object_ports(actor, reference, *, context):
        assert actor == r.actor and reference.bucket_name == 'owned'
        try:
            yield objects
        finally:
            closed.append(reference.object_name)

    service = module.StorageObjectDeletion(reader=r.service, ledger_ports=ledger_ports, object_ports=object_ports)

    def row():
        with engine.connect() as conn:
            return dict(conn.execute(table.select()).mappings().one())

    return SimpleNamespace(**locals())


def test_owner_delete_confirms_object_before_releasing_actual_actor_ledger(deletion):
    s = deletion
    assert s.service.delete('knowledge_base/one', s.r.actor, context=context()) == {'success': True, 'object_name': 'knowledge_base/one'}
    row = s.row()
    assert row['status'] == 'DELETED' and row['delete_flag'] == 'Y' and row['updated_by'] == 'user-a'
    assert s.events == s.closed == ['knowledge_base/one']
    assert all(value == ('tenant-a', 'user-a') for value in s.opened)


@pytest.mark.parametrize('change', [{'knowledge_id': 99}, {'index_name': 'other'}, {'tenant_id': 'tenant-b'}, {'status': 'DELETED'}])
def test_mismatched_or_inactive_source_never_deletes_object(deletion, change):
    s = deletion
    with s.engine.begin() as conn:
        conn.execute(s.table.update().values(**change))
    with pytest.raises(PermissionError):
        s.service.delete('knowledge_base/one', s.r.actor, context=context())
    s.objects.delete.assert_not_called()


def test_non_editor_current_identity_is_denied(deletion):
    s = deletion
    s.r.update('cleanse_knowledge', created_by='other', ingroup_permission='PRIVATE')
    with pytest.raises(PermissionError):
        s.service.delete('knowledge_base/one', s.r.actor, context=context())
    s.objects.delete.assert_not_called()


@pytest.mark.parametrize('ambiguous', ['duplicate', 'cursor'])
def test_ambiguous_ledger_response_fails_closed_before_object_io(deletion, mocker, ambiguous):
    s = deletion
    row = s.row()
    page = SimpleNamespace(items=[row, row] if ambiguous == 'duplicate' else [row],
                           next_cursor='more' if ambiguous == 'cursor' else None)
    query = mocker.patch('infrastructure.rdb.record_store.SQLRecordStore.query', return_value=page)
    with pytest.raises(PermissionError):
        s.service.delete('knowledge_base/one', s.r.actor, context=context())
    assert query.call_count == 1
    s.objects.delete.assert_not_called()
    assert s.row()['status'] == 'COMMITTED'


@pytest.mark.parametrize('dataset', ['cleanse_accounts', 'cleanse_memberships'])
def test_revoked_identity_does_not_delete_object(deletion, dataset):
    s = deletion
    s.r.update(dataset, delete_flag='Y')
    with pytest.raises(PermissionError):
        s.service.delete('knowledge_base/one', s.r.actor, context=context())
    s.objects.delete.assert_not_called()


@pytest.mark.parametrize('error', [Unavailable(), OutcomeUnknown()])
def test_physical_failure_or_unknown_never_releases_charge(deletion, error):
    s = deletion
    s.objects.delete.side_effect = error
    with pytest.raises(type(error)):
        s.service.delete('knowledge_base/one', s.r.actor, context=context())
    assert s.row()['status'] == 'COMMITTED' and s.row()['delete_flag'] == 'N'
    assert s.objects.delete.call_count == 1


def test_unknown_receipt_never_becomes_success_or_ledger_release(deletion):
    s = deletion
    s.objects.delete.return_value = DeleteReceipt('owned', True, WriteOutcome.UNKNOWN)
    s.objects.delete.side_effect = None
    with pytest.raises(OutcomeUnknown):
        s.service.delete('knowledge_base/one', s.r.actor, context=context())
    assert s.row()['status'] == 'COMMITTED'


def test_conflicting_release_is_not_retried(deletion, mocker):
    s = deletion
    patch = mocker.patch('infrastructure.rdb.record_store.SQLRecordStore.patch', side_effect=Conflict())
    with pytest.raises(Conflict):
        s.service.delete('knowledge_base/one', s.r.actor, context=context())
    assert patch.call_count == s.objects.delete.call_count == 1 and s.row()['status'] == 'COMMITTED'


def test_non_kb_path_requires_existing_owner_rule(deletion):
    s = deletion
    with pytest.raises(PermissionError):
        s.service.delete('attachments/other/file.txt', s.r.actor, context=context())
    s.objects.delete.assert_not_called()


def test_current_upload_cleanup_does_not_scan_or_delete_other_keys(deletion):
    s = deletion
    storage = KnowledgeStorageContext('tenant-a', 1, 'kb-one', 'owned')
    s.service.compensate(storage, ['knowledge_base/one'], s.r.actor, context=context())
    assert s.events == ['knowledge_base/one'] and s.row()['status'] == 'DELETED'
    assert s.row()['updated_by'] == 'user-a'


def test_release_invalidates_only_current_tenant_real_shared_cache(deletion):
    from management.services.knowledge_base import usage_cache

    s = deletion
    usage_cache.invalidate_usage_cache()
    try:
        usage_cache._usage_cache.update({'tenant-a': (0, {}), 'tenant-b': (0, {})})
        s.service.delete('knowledge_base/one', s.r.actor, context=context())
        assert 'tenant-a' not in usage_cache._usage_cache and 'tenant-b' in usage_cache._usage_cache
    finally:
        usage_cache.invalidate_usage_cache()


def test_cache_error_keeps_confirmed_delete_success(deletion, mocker, caplog):
    s = deletion
    mocker.patch.object(s.module, 'invalidate_usage_cache', side_effect=RuntimeError('owned cache fault'))
    assert s.service.delete('knowledge_base/one', s.r.actor, context=context())['success']
    assert s.row()['status'] == 'DELETED'
    assert len([r for r in caplog.records if 'Failed to invalidate quota cache' in r.message]) == 1


def test_cleanup_preserves_failed_object_charge_and_continues_selected_next_key(deletion):
    s = deletion
    with s.engine.begin() as conn:
        conn.execute(s.table.insert(), {'storage_object_id': 2, 'tenant_id': 'tenant-a', 'knowledge_id': 1,
            'index_name': 'kb-one', 'bucket_name': 'owned', 'object_name': 'knowledge_base/two', 'raw_bytes': 3,
            'status': 'COMMITTED', 'version': 1, 'created_by': 'user-a', 'delete_flag': 'N'})
    s.objects.delete.side_effect = [Unavailable(), DeleteReceipt('owned', True)]
    storage = KnowledgeStorageContext('tenant-a', 1, 'kb-one', 'owned')
    s.service.compensate(storage, ['knowledge_base/one', 'knowledge_base/two'], s.r.actor, context=context())
    with s.engine.connect() as conn:
        rows = conn.execute(s.table.select().order_by(s.table.c.storage_object_id)).mappings().all()
    assert rows[0]['status'] == 'COMMITTED' and rows[1]['status'] == 'DELETED'
    assert [c.args[0].key for c in s.objects.delete.call_args_list] == ['knowledge_base/one', 'knowledge_base/two']
