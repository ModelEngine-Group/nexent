# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DOC-QUOTA-01/02/03 exercise actual read-only SI quota collaboration."""

from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.knowledge import STORAGE_LEDGER_DATASET
from management.services.knowledge_base import document_admission as module
from management.services.knowledge_base import source_reference
from nexent.storage.errors import (
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_catalog import knowledge
from infrastructure.knowledge_document_quota import bind_document_quota
from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject
from infrastructure.rdb.tenant_config_record import TenantConfig


@pytest.fixture
def admission(mocker):
    engine = sa.create_engine('sqlite://', execution_options={'schema_translate_map': {'nexent': None}})
    for table in (knowledge, KnowledgeStorageObject.__table__, TenantConfig.__table__):
        table.create(engine)
    actor = ServicePrincipal('operator', 'tenant-a')
    with engine.begin() as connection:
        for key, owner, tenant, permission, deleted in [
            (1, 'operator', 'tenant-a', 'PRIVATE', 'N'), (2, 'other', 'tenant-a', 'PRIVATE', 'N'),
            (3, 'operator', 'tenant-b', 'PRIVATE', 'N'), (4, 'operator', 'tenant-a', 'EDIT', 'N'),
            (5, 'operator', 'tenant-a', 'PRIVATE', 'Y'),
        ]:
            connection.execute(knowledge.insert(), {'knowledge_id': key, 'tenant_id': tenant, 'index_name': f'kb-{key}',
                'created_by': owner, 'ingroup_permission': permission, 'delete_flag': deleted, 'knowledge_sources': 'elasticsearch',
                'quota_limit_bytes': 12, 'version': 1})
        for key, kb, tenant, size, status, deleted in [
            (1, 1, 'tenant-a', 10, 'COMMITTED', 'N'), (2, 2, 'tenant-a', 20, 'COMMITTED', 'N'),
            (3, 3, 'tenant-b', 999, 'COMMITTED', 'N'), (4, 4, 'tenant-a', 999, 'COMMITTED', 'N'),
            (5, 5, 'tenant-a', 999, 'COMMITTED', 'N'), (6, 999, 'tenant-a', 999, 'COMMITTED', 'N'),
            (7, 1, 'tenant-a', 999, 'DELETED', 'N'), (8, 1, 'tenant-a', 999, 'COMMITTED', 'Y'),
        ]:
            connection.execute(KnowledgeStorageObject.__table__.insert(), {'storage_object_id': key, 'knowledge_id': kb, 'index_name': f'kb-{kb}', 'tenant_id': tenant,
                'bucket_name': 'files', 'object_name': f'knowledge_base/{key}.txt', 'raw_bytes': size, 'status': status, 'delete_flag': deleted})
    row = {'knowledge_id': 1, 'index_name': 'kb-1', 'tenant_id': actor.tenant_id, 'ingroup_permission': 'PRIVATE',
           'quota_limit_bytes': 12, 'embedding_model_id': 2, 'knowledge_sources': 'elasticsearch', 'deletion_request': None}
    reader = SimpleNamespace(knowledge=Mock(return_value=row))
    opened = []

    @contextmanager
    def ports(principal, *, context):
        assert principal == actor
        stores = bind_document_quota(actor, engine)
        opened.extend(stores)
        try:
            yield stores
        finally:
            for store in stores:
                store.close()

    mocker.patch.object(source_reference, 'MINIO_DEFAULT_BUCKET', 'files')
    yield SimpleNamespace(**locals())
    engine.dispose()


def context():
    return OperationContext('document-quota', monotonic() + 10)


def invoke(s, data=None, **kwargs):
    return module.prepare_document_admission('kb-1', data if data is not None else [
        {'path_or_url': 'new.txt', 'file_size': 2}], s.actor, context=context(), ports=s.ports, reader=s.reader, **kwargs)


def config(s, key, value):
    with s.engine.begin() as connection:
        connection.execute(TenantConfig.__table__.insert(), {'tenant_config_id': connection.execute(
            sa.select(sa.func.count()).select_from(TenantConfig.__table__)).scalar_one() + 1,
            'tenant_id': s.actor.tenant_id, 'config_key': key, 'config_value': value, 'delete_flag': 'N'})


def test_private_source_statistics_exclude_foreign_shared_deleted_and_orphan_rows(admission):
    s = admission
    config(s, 'KB_QUOTA_TENANT_HARD_LIMIT_BYTES', '32')
    invoke(s)
    s.reader.knowledge.assert_called_once()
    assert s.reader.knowledge.call_args.kwargs['edit'] is True
    assert s.reader.knowledge.call_args.args == ('kb-1', s.actor)
    assert s.opened and all(store._closed for store in s.opened)
    with pytest.raises(AppException) as error:
        invoke(s, [{'filename': 'new.txt', 'file_size': 3}])
    assert error.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED
    assert 'Tenant personal KB storage full' in str(error.value)


@pytest.mark.parametrize('key,value,phrase', [
    ('PERSONAL_KB_QUOTA_operator', '11', 'individual'), ('PERSONAL_KB_QUOTA_DEFAULT', '11', 'default'),
    ('PERSONAL_KB_QUOTA_operator', 'broken', 'disabled'), ('PERSONAL_KB_QUOTA_operator', '0', 'disabled'),
])
def test_original_user_limit_and_invalid_value_semantics(admission, key, value, phrase):
    s = admission
    config(s, key, value)
    with pytest.raises(AppException) as error:
        invoke(s)
    assert error.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED and phrase in str(error.value)


def test_individual_limit_overrides_default_and_kb_limit_remains(admission):
    s = admission
    config(s, 'PERSONAL_KB_QUOTA_DEFAULT', '0')
    config(s, 'PERSONAL_KB_QUOTA_operator', '100')
    invoke(s)
    with pytest.raises(AppException, match='KB quota exceeded'):
        invoke(s, [{'filename': 'new.txt', 'file_size': 3}])


def test_resolvable_missing_source_keeps_original_zero_key_membership_semantics(admission):
    s = admission
    config(s, 'PERSONAL_KB_QUOTA_operator', '0')
    for source in ('knowledge_base/missing.txt', 's3://files/missing.txt', '/files/missing.txt'):
        invoke(s, [{'path_or_url': source, 'file_size': 9999}])
    with pytest.raises(AppException, match='disabled'):
        invoke(s, [{'path_or_url': 'unresolved.txt', 'file_size': 1}])


def test_source_dedup_uses_max_positive_size_and_original_field_fallback(admission):
    s = admission
    invoke(s, [{'filename': 'new.txt', 'file_size': 1}, {'path_or_url': 'new.txt', 'file_size': '2'},
               {'path_or_url': '', 'file_size': 999}, {'filename': 'bad.txt', 'file_size': 'bad'},
               {'filename': 'negative.txt', 'file_size': -1}, 'ignored'])


def test_shared_resource_skips_quota_ports_after_current_edit_check(admission):
    s = admission
    s.row['ingroup_permission'] = 'EDIT'
    invoke(s)
    assert not s.opened and s.reader.knowledge.call_count == 1


def test_current_reader_rejection_prevents_all_quota_io(admission):
    s = admission
    s.reader.knowledge.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        invoke(s)
    assert not s.opened


def test_quota_read_failure_is_not_zero_usage_or_retried(admission):
    s = admission
    calls = []

    @contextmanager
    def broken(*args, **kwargs):
        calls.append(True)
        raise Unavailable()
        yield

    with pytest.raises(AppException) as error:
        module.prepare_document_admission('kb-1', [], s.actor, context=context(), reader=s.reader, ports=broken)
    assert error.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE and calls == [True]


def test_duplicate_active_config_is_an_explicit_unavailable_state(admission):
    s = admission
    config(s, 'PERSONAL_KB_QUOTA_operator', '100')
    config(s, 'PERSONAL_KB_QUOTA_operator', '1')
    with pytest.raises(AppException) as error:
        invoke(s)
    assert error.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE


def test_expired_context_never_opens_reader_or_quota_ports(admission):
    s = admission
    with pytest.raises(DeadlineExceeded):
        module.prepare_document_admission('kb-1', [], s.actor, context=OperationContext('expired', monotonic() - 1),
            reader=s.reader, ports=s.ports)
    s.reader.knowledge.assert_not_called()
    assert not s.opened


def test_quota_bindings_reject_every_write(admission):
    s = admission
    with s.ports(s.actor, context=context()) as stores:
        for store in stores:
            dataset = next(iter(store.scope.namespaces))
            with pytest.raises(ScopeDenied):
                store.create(dataset, {}, context=context())
        assert STORAGE_LEDGER_DATASET in stores[1].scope.namespaces


def test_pending_preserves_zero_valued_reference_keys(admission):
    s = admission
    data = [{'path_or_url': 's3://files/missing.txt', 'file_size': 999},
            {'filename': 'plain.txt', 'file_size': 2}, {'filename': 'plain.txt', 'file_size': 1}]
    with s.ports(s.actor, context=context()) as (_, ledger, _):
        assert module._pending(ledger, s.row, data, context()) == 2


def test_duplicate_private_catalog_is_not_arbitrarily_collapsed(admission):
    s = admission
    with s.engine.begin() as connection:
        connection.execute(knowledge.insert(), {'knowledge_id': 6, 'tenant_id': 'tenant-a', 'index_name': 'kb-2',
            'created_by': 'other', 'ingroup_permission': 'PRIVATE', 'delete_flag': 'N', 'version': 1})
    with pytest.raises(AppException) as error:
        invoke(s)
    assert error.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE


def test_actor_scope_mismatch_cannot_be_replaced_with_creator_identity(admission):
    s = admission

    @contextmanager
    def wrong_actor(*args, **kwargs):
        stores = bind_document_quota(ServicePrincipal('creator', s.actor.tenant_id), s.engine)
        try:
            yield stores
        finally:
            for store in stores:
                store.close()

    with pytest.raises(AppException) as error:
        module.prepare_document_admission('kb-1', [], s.actor, context=context(), reader=s.reader, ports=wrong_actor)
    assert error.value.error_code == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE


def test_later_private_page_participates_in_tenant_total(admission):
    s = admission
    with s.engine.begin() as connection:
        connection.execute(knowledge.insert(), [{'knowledge_id': key, 'tenant_id': 'tenant-a',
            'index_name': f'page-{key}', 'created_by': 'other', 'ingroup_permission': 'PRIVATE',
            'delete_flag': 'N', 'version': 1} for key in range(1000, 1501)])
        connection.execute(KnowledgeStorageObject.__table__.insert(), {'storage_object_id': 1000,
            'knowledge_id': 1500, 'index_name': 'page-1500', 'tenant_id': 'tenant-a', 'bucket_name': 'files',
            'object_name': 'later-page.txt', 'raw_bytes': 1000, 'status': 'COMMITTED', 'delete_flag': 'N'})
    config(s, 'KB_QUOTA_TENANT_HARD_LIMIT_BYTES', '32')
    with pytest.raises(AppException, match='Tenant personal KB storage full'):
        invoke(s)


def test_zero_personal_and_kb_limits_keep_original_empty_pending_behavior(admission):
    s = admission
    config(s, 'PERSONAL_KB_QUOTA_operator', '0')
    s.row['quota_limit_bytes'] = 0
    invoke(s, [])


def test_invalid_tenant_limit_remains_unlimited(admission):
    s = admission
    config(s, 'KB_QUOTA_TENANT_HARD_LIMIT_BYTES', 'invalid')
    invoke(s)


def test_existing_cancellation_does_not_become_quota_unavailable(admission):
    from threading import Event

    s = admission
    cancelled = Event()
    cancelled.set()
    with pytest.raises(OperationCancelled):
        module.prepare_document_admission('kb-1', [], s.actor,
            context=OperationContext('cancelled', monotonic() + 10, cancelled=cancelled), reader=s.reader, ports=s.ports)
    assert not s.opened and s.reader.knowledge.call_count == 0
