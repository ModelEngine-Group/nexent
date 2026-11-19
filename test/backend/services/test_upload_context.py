# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UPLOAD-CONTEXT-01 reads narrow SI metadata before existing upload DAC."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import FieldPatch, StorageScope

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def upload(resources, mocker):  # noqa: F811
    from management.services.file.upload_context import UploadContextReader

    from infrastructure import upload_context as module

    _, update, engine, tables = resources
    mocker.patch.object(module, 'knowledge', tables['cleanse_knowledge'])
    actor = ServicePrincipal('user-a', 'tenant-a')
    opened, closed = [], []

    @contextmanager
    def ports(principal, *, context):
        assert principal == actor
        identity = bind_cleanse_resources(StorageScope('management', actor.tenant_id, actor.user_id,
            {'cleanse_memberships', 'cleanse_accounts'}), engine)
        handles = [identity]

        def metadata():
            opened.append(principal)
            port = module.bind_upload_context(principal, engine)
            handles.append(port)
            return port

        try:
            yield identity, metadata
        finally:
            for port in handles:
                port.close()
            closed.append(True)

    reader = UploadContextReader(ports=ports, bucket_name='test-bucket')
    return SimpleNamespace(**locals())


def test_resolve_requires_tenant_owned_kb_and_preserves_context(upload):
    from contracts.knowledge import KnowledgeStorageContext

    s = upload
    result = s.reader.read('kb-one', s.actor, context=context())
    assert result == KnowledgeStorageContext('tenant-a', 1, 'kb-one', 'test-bucket', 'EDIT')
    assert s.opened == [s.actor] and s.closed == [True]


def test_missing_and_foreign_kb_return_none(upload):
    s = upload
    assert s.reader.read('missing', s.actor, context=context()) is None
    s.update('cleanse_knowledge', tenant_id='tenant-b')
    assert s.reader.read('kb-one', s.actor, context=context()) is None


@pytest.mark.parametrize(('deleted', 'present'), [('Y', False), ('N', True), ('X', True)])
def test_original_non_deleted_filter_is_preserved(upload, deleted, present):
    s = upload
    s.update('cleanse_knowledge', delete_flag=deleted)
    assert (s.reader.read('kb-one', s.actor, context=context()) is not None) == present


def test_empty_index_does_not_open_resources(upload):
    s = upload
    assert s.reader.read(None, s.actor, context=context()) is None
    assert not s.opened and not s.closed


def test_resolve_requires_configured_bucket(upload):
    from management.services.file.upload_context import UploadContextReader

    s = upload
    with pytest.raises(RuntimeError, match='default bucket'):
        UploadContextReader(ports=s.ports, bucket_name='').read('kb-one', s.actor, context=context())


@pytest.mark.parametrize('dataset', ['cleanse_accounts', 'cleanse_memberships'])
def test_disabled_actor_cannot_open_catalog(upload, dataset):
    s = upload
    s.update(dataset, delete_flag='Y')
    with pytest.raises(ScopeDenied):
        s.reader.read('kb-one', s.actor, context=context())
    assert not s.opened


def test_identity_revoked_before_response_is_refused(upload, mocker):
    from management.services.file import upload_context as module

    s = upload
    original, calls = module.quota_identity_roles, []

    def authorize(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            s.update('cleanse_memberships', delete_flag='Y')
        return original(*args, **kwargs)

    mocker.patch.object(module, 'quota_identity_roles', side_effect=authorize)
    with pytest.raises(ScopeDenied):
        s.reader.read('kb-one', s.actor, context=context())
    assert len(calls) == 2 and s.closed == [True]


def test_catalog_is_read_only(upload):
    from infrastructure.upload_context import DATASET

    s = upload
    port = s.module.bind_upload_context(s.actor, s.engine)
    try:
        with pytest.raises(ScopeDenied):
            port.patch(DATASET, 1, FieldPatch(set_values={'index_name': 'changed'}), expected=None, context=context())
    finally:
        port.close()


def test_duplicate_index_keeps_original_first_mapping(upload):
    s = upload
    with s.engine.begin() as conn:
        conn.execute(s.tables['cleanse_knowledge'].insert(), {
            'knowledge_id': 2, 'tenant_id': 'tenant-a', 'index_name': 'kb-one',
            'created_by': 'other', 'ingroup_permission': 'PRIVATE',
            'knowledge_sources': 'elasticsearch', 'delete_flag': 'N',
        })
    assert s.reader.read('kb-one', s.actor, context=context()).knowledge_id == 1


def test_metadata_resolution_does_not_grant_edit_access(upload):
    from management.services.knowledge_base.file_authorization import (
        KnowledgeFileAuthorization,
    )

    s = upload
    s.update('cleanse_knowledge', created_by='other', ingroup_permission='PRIVATE')
    assert s.reader.read('kb-one', s.actor, context=context()) is not None
    permissions = bind_cleanse_resources(StorageScope('management', s.actor.tenant_id, s.actor.user_id, {
        'cleanse_knowledge', 'cleanse_memberships', 'cleanse_accounts', 'cleanse_group_memberships', 'cleanse_groups',
    }), s.engine)
    try:
        with pytest.raises(ScopeDenied):
            KnowledgeFileAuthorization(permissions, user_id=s.actor.user_id).resolve_knowledge(1, edit=True, context=context())
    finally:
        permissions.close()
