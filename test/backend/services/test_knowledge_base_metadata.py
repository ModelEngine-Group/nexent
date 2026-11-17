# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-KB-FINAL-01/02/03: one scoped SI metadata transaction."""

import asyncio
import base64
import json
from contextlib import contextmanager
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_CONVERSATIONS as CONVERSATIONS,
)
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_TAG_ASSIGNMENTS as TAGS,
)
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_TAG_PROJECTIONS as PROJECTIONS,
)
from contracts.knowledge_base_metadata import (
    KNOWLEDGE_TOOL_BINDINGS as TOOLS,
)
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from management.services.knowledge_base.base_deletion import (
    request_knowledge_base_deletion,
)
from management.services.knowledge_base.base_metadata import (
    finalize_knowledge_base_deletion,
)
from nexent.storage.errors import Conflict, OperationCancelled, ScopeDenied
from nexent.storage.models import FieldPatch, StorageScope

from infrastructure.rdb import knowledge_base_metadata as mapping
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads,  # noqa: F401
)
from test.backend.services.test_knowledge_upload_admission import (
    admission,  # noqa: F401
)


@pytest.fixture
def metadata(sqlite_threads, admission, monkeypatch):  # noqa: F811
    s = admission
    schema = sa.MetaData()

    def clone(table, name, names=None):
        return sa.Table(name, schema, *[
            sa.Column(c.name, sa.JSON if isinstance(c.type, sa.JSON) else c.type,
                      primary_key=c.primary_key, nullable=c.nullable)
            for c in table.c if names is None or c.name in names
        ])

    audit = {'create_time', 'update_time', 'created_by', 'updated_by', 'delete_flag'}
    tables = {
        'tools': clone(mapping.tools, 'tools', audit | {'tool_instance_id', 'version_no', 'tenant_id', 'tool_id', 'params'}),
        'tool_info': clone(mapping.tool_info, 'tool_info', {'tool_id', 'name', 'delete_flag'}),
        'conversations': clone(mapping.conversations, 'conversations', audit | {'conversation_id', 'knowledge_scope', 'workbench_config', 'workbench_config_version'}),
        'memberships': clone(mapping.memberships, 'memberships', {'user_tenant_id', 'user_id', 'tenant_id', 'delete_flag'}),
        'tags': clone(mapping.tags, 'tags'), 'projections': clone(mapping.projections, 'projections'),
    }
    for name, table in tables.items():
        monkeypatch.setattr(mapping, name, table)
    schema.create_all(s.engine)

    def encoded(provider, index, doc='source.txt'):
        return base64.urlsafe_b64encode(json.dumps([provider, index, doc], separators=(',', ':')).encode()).decode()

    def scope(*ids):
        return {'local': {'mode': 'selected', 'knowledge_ids': list(ids)},
                'aidp': {'mode': 'selected', 'kds_ids': ['cloud']}}

    with s.engine.begin() as conn:
        conn.execute(tables['tool_info'].insert(), [{'tool_id': 1, 'name': 'knowledge_base_search', 'delete_flag': 'N'},
                                                   {'tool_id': 2, 'name': 'other', 'delete_flag': 'N'}])
        conn.execute(tables['tools'].insert(), [{'tool_instance_id': i, 'version_no': v, 'tenant_id': t, 'tool_id': k,
                                                   'params': {'index_names': ['kb-one', 'other'], 'keep': True},
                                                   'created_by': 'owner', 'delete_flag': 'N'}
                                                for i, v, t, k in ((1, 0, 'tenant-a', 1), (1, 1, 'tenant-a', 1),
                                                                    (2, 0, 'foreign', 1), (3, 0, 'tenant-a', 2))])
        conn.execute(tables['memberships'].insert(), [{'user_tenant_id': i, 'user_id': u, 'tenant_id': t, 'delete_flag': 'N'}
                                                      for i, u, t in ((1, 'user-a', 'tenant-a'), (2, 'other-reader', 'tenant-a'),
                                                                      (3, 'foreign-user', 'foreign'))])
        conn.execute(tables['conversations'].insert(), [{'conversation_id': i, 'created_by': u, 'delete_flag': 'N',
                                                            'knowledge_scope': scope('1', '2'),
                                                            'workbench_config': {'knowledge_scope': scope('1'), 'keep': True},
                                                            'workbench_config_version': 5}
                                                         for i, u in ((1, 'user-a'), (2, 'other-reader'), (3, 'foreign-user'))])
        targets = [('tenant-a', 'knowledge_base', 'kb-one'),
                   ('tenant-a', 'knowledge_document', encoded('local', 'kb-one')),
                   ('tenant-a', 'knowledge_document', encoded('aidp', 'kb-one')),
                   ('tenant-a', 'knowledge_document', encoded('local', 'other')),
                   ('foreign', 'knowledge_base', 'kb-one'),
                   ('tenant-a', 'knowledge_document', 'malformed')]
        conn.execute(tables['tags'].insert(), [{'assignment_id': i, 'tenant_id': t, 'resource_type': k, 'resource_id': r,
                                                   'created_by': 'owner', 'delete_flag': 'N'} for i, (t, k, r) in enumerate(targets, 1)])
        conn.execute(tables['projections'].insert(), [{'projection_id': i, 'tenant_id': t, 'provider': p, 'knowledge_base_id': k,
                                                          'created_by': 'owner', 'delete_flag': 'N'}
                                                       for i, t, p, k in ((1, 'tenant-a', 'local', 'kb-one'),
                                                                          (2, 'tenant-a', 'aidp', 'kb-one'),
                                                                          (3, 'tenant-a', 'local', 'other'),
                                                                          (4, 'foreign', 'local', 'kb-one'))])
    records = mapping.bind_base_metadata_records(StorageScope('management', 'tenant-a', 'user-a', {
        KB, FILES, TOOLS, CONVERSATIONS, TAGS, PROJECTIONS,
    }), s.engine)
    row = request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())
    s.records.patch(KB, 1, FieldPatch(set_values={
        'deletion_request': {**row['deletion_request'], 'phase': 'metadata_pending'},
    }), expected=None, context=context())
    row = s.records.get(KB, 1, context=context())

    def rows(name):
        with s.engine.connect() as conn:
            return [dict(row) for row in conn.execute(sa.select(tables[name])).mappings()]

    try:
        yield SimpleNamespace(**locals())
    finally:
        records.close()


def test_success_removes_only_owned_bindings_in_one_transaction(metadata):
    m, s = metadata, metadata.s
    result = finalize_knowledge_base_deletion(m.records, s.authorized, m.row, s.actor, context=context())
    assert result['delete_flag'] == 'Y' and result['deletion_request']['phase'] == 'deleted'
    assert s.records.get(KB, 1, context=context()) is None
    tools = m.rows('tools')
    assert [row['params']['index_names'] for row in tools] == [['other'], ['other'], ['kb-one', 'other'], ['kb-one', 'other']]
    assert all(row['params']['keep'] is True for row in tools)
    assert all(row['updated_by'] == 'user-a' and row['created_by'] == 'owner' for row in tools[:2])
    conversations = m.rows('conversations')
    for row in conversations[:2]:
        assert row['knowledge_scope']['local']['knowledge_ids'] == ['2']
        assert row['knowledge_scope']['aidp']['kds_ids'] == ['cloud']
        assert row['workbench_config']['knowledge_scope']['local'] == {'mode': 'disabled', 'knowledge_ids': []}
        assert row['workbench_config']['keep'] and row['workbench_config_version'] == 6
    assert conversations[1]['created_by'] == 'other-reader'
    assert conversations[2]['workbench_config_version'] == 5
    assert [row['delete_flag'] for row in m.rows('tags')] == ['Y', 'Y', 'N', 'N', 'N', 'N']
    assert [row['projection_id'] for row in m.rows('projections')] == [2, 3, 4]


@pytest.mark.parametrize('change', [{'phase': 'files'}, {'phase': 'collection_submitting'}, {'user_id': 'other'}])
def test_unconfirmed_or_foreign_execution_cannot_change_metadata(metadata, change):
    m = metadata
    row = {**m.row, 'deletion_request': {**m.row['deletion_request'], **change}}
    with pytest.raises((ScopeDenied, Conflict)):
        finalize_knowledge_base_deletion(m.records, m.s.authorized, row, m.s.actor, context=context())
    assert all(row['delete_flag'] == 'N' for row in m.rows('tags'))
    assert m.s.records.get(KB, 1, context=context()) == m.row


def test_failure_after_binding_updates_rolls_back_every_change(metadata, monkeypatch):
    m = metadata
    delete = type(m.records).delete

    def fail(self, dataset, *args, **kwargs):
        if dataset == KB:
            raise ValueError('controlled final delete failure')
        return delete(self, dataset, *args, **kwargs)

    monkeypatch.setattr(type(m.records), 'delete', fail)
    with pytest.raises(ValueError, match='controlled final'):
        finalize_knowledge_base_deletion(m.records, m.s.authorized, m.row, m.s.actor, context=context())
    assert all(row['params']['index_names'] == ['kb-one', 'other'] for row in m.rows('tools'))
    assert all(row['workbench_config_version'] == 5 for row in m.rows('conversations'))
    assert all(row['delete_flag'] == 'N' for row in m.rows('tags'))
    assert len(m.rows('projections')) == 4
    assert m.s.records.get(KB, 1, context=context()) == m.row


def test_live_revocation_rejects_before_any_binding_change(metadata):
    m = metadata
    m.s.update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        finalize_knowledge_base_deletion(m.records, m.s.authorized, m.row, m.s.actor, context=context())
    assert m.s.records.get(KB, 1, context=context()) == m.row
    assert len(m.rows('projections')) == 4


def test_no_change_does_not_increment_workbench_version(metadata):
    m = metadata
    with m.s.engine.begin() as conn:
        conn.execute(m.tables['conversations'].update().values(knowledge_scope=None,
                     workbench_config={'knowledge_scope': m.scope('2'), 'keep': True}))
    finalize_knowledge_base_deletion(m.records, m.s.authorized, m.row, m.s.actor, context=context())
    assert all(row['workbench_config_version'] == 5 for row in m.rows('conversations'))


def test_only_confirmed_files_are_soft_deleted_with_metadata(metadata):
    m = metadata
    intent = KnowledgeDeletionIntent(knowledge_id=1, file_id='b' * 32, file_version=0, user_id='user-a',
                                     scope='full', index_name='kb-one', filename='b.txt', object_name=None, source=None)
    m.s.records.create(FILES, {'file_id': intent.file_id, 'knowledge_id': 1, 'index_name': 'kb-one',
                               'status': 'DELETED', 'stage': 'DELETE_DONE', 'original_filename': 'b.txt',
                               'source_generation': 0, 'processing_attempt': 0, 'deletion_request': intent.model_dump(mode='json'),
                               'deleted_vector_count': 0}, context=context())
    result = finalize_knowledge_base_deletion(m.records, m.s.authorized, m.row, m.s.actor, context=context())
    assert result['metadata_cleanup']['files_deleted'] == 1
    with m.s.engine.connect() as conn:
        file = conn.execute(sa.select(m.s.files)).mappings().one()
    assert file['delete_flag'] == 'Y' and file['updated_by'] == 'user-a'


def test_unfinished_file_rolls_back_parent_and_leaves_all_bindings(metadata):
    m = metadata
    m.s.records.create(FILES, {'file_id': 'b' * 32, 'knowledge_id': 1, 'index_name': 'kb-one',
                               'status': 'DELETE_REQUESTED', 'stage': 'DELETE_RUNTIME_PENDING',
                               'original_filename': 'b.txt', 'source_generation': 0, 'processing_attempt': 0}, context=context())
    with pytest.raises(Conflict):
        finalize_knowledge_base_deletion(m.records, m.s.authorized, m.row, m.s.actor, context=context())
    assert m.s.records.get(KB, 1, context=context()) == m.row
    assert all(row['params']['index_names'] == ['kb-one', 'other'] for row in m.rows('tools'))


def test_coordinator_finishes_metadata_pending_without_any_new_rpc(metadata, monkeypatch):
    from management.services.knowledge_base.base_deletion_coordinator import (
        KnowledgeBaseDeletionCoordinator,
    )

    m = metadata

    @contextmanager
    def ports(actor, *, context):
        assert actor == m.s.actor
        yield m.records, m.s.authorized

    async def blocking(name, fn, *args, **kwargs):
        kwargs.pop('lane')
        kwargs.pop('owner')
        return await asyncio.to_thread(fn, *args, **kwargs)

    monkeypatch.setattr('management.services.knowledge_base.base_deletion_coordinator.run_blocking', blocking)
    client = SimpleNamespace(delete_knowledge_base=AsyncMock(), inspect_knowledge_base_deletion=AsyncMock())
    coordinator = KnowledgeBaseDeletionCoordinator(None, client, ports=ports, metadata_ports=ports)
    result = asyncio.run(coordinator.request('kb-one', m.s.actor))
    assert result['deletion_request']['phase'] == 'deleted' and result['delete_flag'] == 'Y'
    client.delete_knowledge_base.assert_not_awaited()
    client.inspect_knowledge_base_deletion.assert_not_awaited()


def test_tag_deletion_does_not_skip_rows_after_first_page(metadata):
    m = metadata
    with m.s.engine.begin() as conn:
        conn.execute(m.tables['tags'].insert(), [
            {'assignment_id': value, 'tenant_id': 'tenant-a', 'resource_type': 'knowledge_base',
             'resource_id': 'kb-one', 'delete_flag': 'N'} for value in range(1000, 1201)
        ])
    result = finalize_knowledge_base_deletion(m.records, m.s.authorized, m.row, m.s.actor, context=context())
    assert result['metadata_cleanup']['tag_assignments_deleted'] == 203
    assert sum(row['delete_flag'] == 'Y' for row in m.rows('tags')) == 203


def test_row_lock_precedes_merge_and_preserves_newly_committed_fields(metadata, monkeypatch):
    m = metadata
    patch = type(m.records).patch
    changed = []

    def before_lock(self, dataset, key, values, **kwargs):
        if dataset == TOOLS and key == (1, 0) and not values.set_values and not changed:
            # Simulate a collaborator committing before this transaction acquires its row lock.
            changed.append(True)
            patch(self, dataset, key, FieldPatch(set_values={
                'params': {'index_names': ['kb-one', 'new-selection'], 'new-field': 42},
            }), **kwargs)
        return patch(self, dataset, key, values, **kwargs)

    monkeypatch.setattr(type(m.records), 'patch', before_lock)
    finalize_knowledge_base_deletion(m.records, m.s.authorized, m.row, m.s.actor, context=context())
    assert changed == [True]
    assert m.rows('tools')[0]['params'] == {'index_names': ['new-selection'], 'new-field': 42}


@pytest.mark.parametrize('action', ['revoke', 'cancel'])
def test_late_revocation_or_cancellation_rolls_back_all_metadata(metadata, monkeypatch, action):
    m = metadata
    stopped = Event()
    operation = replace(context(), cancelled=stopped)
    delete = type(m.records).delete

    def after_ledger_delete(self, dataset, *args, **kwargs):
        result = delete(self, dataset, *args, **kwargs)
        if dataset == PROJECTIONS:
            if action == 'revoke':
                m.s.update('cleanse_memberships', delete_flag='Y')
            else:
                stopped.set()
        return result

    monkeypatch.setattr(type(m.records), 'delete', after_ledger_delete)
    with pytest.raises(ScopeDenied if action == 'revoke' else OperationCancelled):
        finalize_knowledge_base_deletion(m.records, m.s.authorized, m.row, m.s.actor, context=operation)
    assert m.s.records.get(KB, 1, context=context()) == m.row
    assert all(row['params']['index_names'] == ['kb-one', 'other'] for row in m.rows('tools'))
    assert all(row['delete_flag'] == 'N' for row in m.rows('tags'))
    assert len(m.rows('projections')) == 4


@pytest.mark.parametrize('different_revision,expected', [(False, 1), (True, 2)])
def test_source_summary_counts_confirmed_exact_resource_identities(metadata, different_revision, expected):
    m = metadata
    for number, file_id in enumerate(('b' * 32, 'c' * 32)):
        source = {'space': 'files', 'key': 'source.txt', 'version': 'etag:' + str(number if different_revision else 0),
                  'sha256': 'a' * 64}
        intent = KnowledgeDeletionIntent(knowledge_id=1, file_id=file_id, file_version=0, user_id='user-a', scope='full',
                                         index_name='kb-one', filename='source.txt', object_name='source.txt', source=source)
        m.s.records.create(FILES, {'file_id': file_id, 'knowledge_id': 1, 'index_name': 'kb-one',
                                   'status': 'DELETED', 'stage': 'DELETE_DONE', 'original_filename': 'source.txt',
                                   'object_name': 'source.txt', 'source_generation': 0, 'processing_attempt': 0,
                                   'deletion_request': intent.model_dump(mode='json'), 'deleted_vector_count': 0,
                                   'source_space': source['space'], 'source_key': source['key'],
                                   'source_revision': source['version'], 'source_sha256': source['sha256']}, context=context())
    result = finalize_knowledge_base_deletion(m.records, m.s.authorized, m.row, m.s.actor, context=context())
    assert result['metadata_cleanup']['files_deleted'] == 2
    assert result['metadata_cleanup']['source_objects_deleted'] == expected
