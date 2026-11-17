# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-COLLECTION-03: actual Runtime records fence a one-shot physical cleanup."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from contracts.knowledge_base_deletion import (
    BASE_DELETION_DATASET as BASE,
)
from contracts.knowledge_base_deletion import (
    RUNTIME_FILES as FILES,
)
from contracts.knowledge_base_deletion import (
    RUNTIME_JOBS as JOBS,
)
from contracts.knowledge_base_deletion import (
    KnowledgeBaseDelete,
    KnowledgeBaseDeleteGrant,
    KnowledgeBaseDeleteLookup,
)
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import StorageScope
from runtime.knowledge_base.base_deletion import KnowledgeBaseDeletionJournal

from infrastructure.rdb import knowledge_base_deletions as mapping
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def journal(monkeypatch):
    metadata = sa.MetaData()

    def clone(table, name):
        return sa.Table(name, metadata, *[
            sa.Column(c.name, sa.JSON(none_as_null=True) if isinstance(c.type, sa.JSON) else c.type,
                      primary_key=c.primary_key, nullable=c.nullable)
            for c in table.c
        ])

    base = clone(mapping.deletions, 'base')
    jobs, files = clone(mapping.jobs, 'jobs'), clone(mapping.files, 'files')
    monkeypatch.setattr(mapping, 'deletions', base)
    monkeypatch.setattr(mapping, 'jobs', jobs)
    monkeypatch.setattr(mapping, 'files', files)
    engine = sa.create_engine('sqlite://')
    metadata.create_all(engine)
    records = mapping.bind_base_deletion_records(StorageScope('runtime', 'tenant-a', 'user-a', {BASE, JOBS, FILES}), engine)
    actor = SimpleNamespace(user_id='user-a', tenant_id='tenant-a')
    request = KnowledgeBaseDelete(knowledge_id=1, idempotency_key='delete-kb')
    grant = KnowledgeBaseDeleteGrant(knowledge_id=1, collection='kb-one')
    policy = KnowledgeBaseDeletionJournal(records, actor, grant)
    try:
        yield SimpleNamespace(**locals())
    finally:
        records.close()
        engine.dispose()


def test_empty_kb_reserves_exactly_one_owner_and_repeated_request_does_not_own_again(journal):
    s = journal
    row, owner = s.policy.reserve(s.request, context=context())
    assert owner and row['status'] == 'deleting'
    assert row['created_by'] == 'user-a' and row['tenant_id'] == 'tenant-a'
    assert s.policy.reserve(s.request, context=context()) == (row, False)
    state = s.policy.finish(row, physical_absence_confirmed=True, context=context())
    assert state.status == 'deleted' and state.physical_cleanup_complete
    row, owner = s.policy.reserve(s.request, context=context())
    assert not owner and row['status'] == 'deleted'


def test_lookup_never_crosses_actor_or_collection(journal):
    s = journal
    row, _ = s.policy.reserve(s.request, context=context())
    lookup = KnowledgeBaseDeleteLookup(knowledge_id=1, job_id=row['job_id'])
    with pytest.raises(ScopeDenied):
        KnowledgeBaseDeletionJournal(s.records, SimpleNamespace(user_id='other', tenant_id='tenant-a'), s.grant)
    other = KnowledgeBaseDeletionJournal(s.records, s.actor, s.grant.model_copy(update={'collection': 'other'}))
    with pytest.raises(Conflict):
        other.record(lookup, context=context())


@pytest.mark.parametrize('changed', [
    {'latest_version': 1, 'tombstone_version': 0}, {'active_job_id': 'a' * 32},
    {'visible_job_id': 'b' * 32}, {'visible_generation': 'c' * 32}, {'visible_version': 0},
])
def test_any_unfenced_or_visible_file_blocks_collection_cleanup(journal, changed):
    s = journal
    with s.engine.begin() as connection:
        connection.execute(s.files.insert(), {'record_id': 'a' * 32, 'tenant_id': 'tenant-a', 'knowledge_id': 1,
            'file_id': 'b' * 32, 'latest_version': 0, 'tombstone_version': 0, 'revision': 1,
            'delete_flag': 'N', 'created_by': 'user-a', 'updated_by': 'user-a', 'create_time': datetime.now(UTC), 'update_time': datetime.now(UTC), **changed})
    with pytest.raises(Conflict):
        s.policy.reserve(s.request, context=context())
    assert s.records.count(BASE, sa_query(), context=context()) == 0


def sa_query():
    from nexent.storage.models import RecordQuery
    return RecordQuery()


def test_unended_writer_blocks_cleanup_even_without_a_visible_file(journal):
    s = journal
    with s.engine.begin() as connection:
        connection.execute(s.jobs.insert(), {'job_id': 'a' * 32, 'tenant_id': 'tenant-a', 'user_id': 'writer-b',
            'knowledge_id': 1, 'file_id': 'b' * 32, 'file_version': 0, 'operation': 'upload', 'request_hash': 'a' * 64,
            'request_payload': {}, 'status': 'failed', 'write_started': True, 'writer_ended': False,
            'reconcile_required': True, 'physical_cleanup_complete': False, 'revision': 1, 'delete_flag': 'N',
            'created_by': 'writer-b', 'updated_by': 'writer-b', 'create_time': datetime.now(UTC), 'update_time': datetime.now(UTC)})
    with pytest.raises(Conflict):
        s.policy.reserve(s.request, context=context())


def test_terminal_requires_actual_absence_confirmation(journal):
    s = journal
    row, _ = s.policy.reserve(s.request, context=context())
    with pytest.raises(Conflict):
        s.policy.finish(row, physical_absence_confirmed=False, context=context())
    assert s.records.get(BASE, row['job_id'], context=context())['status'] == 'deleting'


def test_runtime_barrier_checks_all_file_pages(journal):
    s = journal
    with s.engine.begin() as connection:
        connection.execute(s.files.insert(), [{'record_id': f'{number:032x}', 'tenant_id': 'tenant-a', 'knowledge_id': 1,
            'file_id': f'{number:032x}', 'latest_version': 0, 'tombstone_version': 0 if number < 200 else -1,
            'revision': 1, 'delete_flag': 'N', 'created_by': 'user-a', 'updated_by': 'user-a',
            'create_time': datetime.now(UTC), 'update_time': datetime.now(UTC)} for number in range(201)])
    with pytest.raises(Conflict):
        s.policy.reserve(s.request, context=context())
