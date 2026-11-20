# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current Management DAC surrounds redacted legacy vector evidence."""

import hashlib
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from management.services.knowledge_base.legacy_vectors import LegacyVectorInspector
from management.services.knowledge_base.legacy_chunk_migration import LegacyChunkMigration
from contracts.agentos_knowledge import KnowledgeChunk
from contracts.knowledge_chunk_mutation import ChunkMutationState, ChunkMutationTarget
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from contracts.knowledge_maintenance import LEGACY_VECTOR_METADATA
from nexent.storage.errors import Conflict, ScopeDenied, Unavailable
from nexent.storage.models import Page, StorageScope

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import cleanse_resources
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)


@pytest.fixture
def inspection(sqlite_threads, resources):
    _, update, engine, _ = resources
    update('cleanse_knowledge', created_by='owner')
    actor = ServicePrincipal('user-a', 'tenant-a')
    closed, frames = [], []
    @contextmanager
    def resource_ports(tenant_id, user_id, *, context):
        port = cleanse_resources.bind_cleanse_resources(StorageScope('management', tenant_id, user_id,
            set(cleanse_resources.TABLES)), engine)
        try: yield port
        finally: port.close(); closed.append('resources')
    records = Mock(scope=StorageScope('management', actor.tenant_id, actor.user_id, {'legacy_knowledge_documents','legacy_knowledge_vector_metadata'}))
    records.get.return_value = {'collection': 'kb-one', 'tenant_id': 'tenant-a', 'revision': 'a'*64, 'dimensions': 2, 'metric': 'cosine'}
    row = {'document_id': 'raw-private-id', 'tenant_id': 'tenant-a', 'revision': '1:1', 'properties': {
        'path_or_url': 'https://secret:password@host/file?token=private', 'file_id': 'b'*32, 'index': 0, 'embedding': [1., 0.],
        'content': 'private content'}}
    records.count.return_value = 1; records.query.return_value = Page((row,))
    @contextmanager
    def vectors(*args, **kwargs):
        try: yield records
        finally: closed.append('vectors')
    return SimpleNamespace(service=LegacyVectorInspector(resources=resource_ports, vectors=vectors), actor=actor,
        records=records, row=row, update=update, closed=closed, frames=frames)


def scan(s):
    return s.service.scan(1, s.actor, s.frames.append, page_size=2, context=context())


def test_reports_observed_values_and_hashes_without_original_url_content_or_vector(inspection):
    s = inspection; result = scan(s)
    assert result['documents'] == 1 and result['documents_with_issues'] == 0
    frame, = s.frames; item, = frame.documents
    assert frame.actor_id == 'user-a' and item.file_id == 'b'*32 and item.chunk_index == 0 and item.dimensions == 2
    assert item.source_reference_hash == hashlib.sha256(s.row['properties']['path_or_url'].encode()).hexdigest()
    assert all(value not in frame.model_dump_json() for value in ('secret', 'password', 'token', 'private content', 'raw-private-id', '[1.0'))
    assert s.closed == ['vectors', 'resources']


@pytest.mark.parametrize('change', ['revoked', 'private', 'read-only', 'deleting'])
def test_discovery_never_bypasses_current_edit_authority(inspection, change):
    s = inspection
    if change == 'revoked': s.update('cleanse_memberships', delete_flag='Y')
    elif change == 'deleting': s.update('cleanse_knowledge', deletion_request={'pending': True})
    else: s.update('cleanse_knowledge', ingroup_permission='PRIVATE' if change == 'private' else 'READ_ONLY')
    with pytest.raises(ScopeDenied): scan(s)
    s.records.get.assert_not_called()


@pytest.mark.parametrize('properties,code', [
    ({'path_or_url': None}, 'SOURCE_REFERENCE_UNKNOWN'), ({'file_id': ''}, 'LEGACY_FILE_ID_UNRESOLVED'),
    ({'index': True}, 'CHUNK_INDEX_UNKNOWN'), ({'tenant_id': 'tenant-b'}, 'LEGACY_DOCUMENT_TENANT_CONFLICT'),
    ({'embedding': None}, 'VECTOR_MISSING_OR_INVALID'), ({'embedding': []}, 'VECTOR_DIMENSIONS_INVALID'),
    ({'embedding': [0., 0.]}, 'VECTOR_ZERO_NORM'), ({'embedding': [float('nan'), 0.]}, 'VECTOR_VALUES_INVALID'),
    ({'embedding': [True, 0.]}, 'VECTOR_VALUES_INVALID'), ({'embedding': [10**1000, 0.]}, 'VECTOR_VALUES_INVALID'),
    ({'embedding': [1.]}, 'VECTOR_DIMENSION_MISMATCH'),
])
def test_inconsistent_legacy_fields_are_reported_without_inventing_missing_identity(inspection, properties, code):
    s = inspection; s.row['properties'].update(properties)
    assert scan(s)['documents_with_issues'] == 1
    assert code in s.frames[0].documents[0].issues


def test_permissions_changed_during_scan_discard_page_and_do_not_restart(inspection):
    s = inspection
    def changed(*args, **kwargs):
        s.update('cleanse_memberships', delete_flag='Y')
        return Page((s.row,))
    s.records.query.side_effect = changed
    with pytest.raises(ScopeDenied): scan(s)
    assert s.frames == [] and s.records.query.call_count == 1


def test_missing_records_do_not_satisfy_snapshot_count(inspection):
    s = inspection; s.records.count.return_value = 2
    with pytest.raises(Conflict): scan(s)
    assert s.closed == ['vectors', 'resources']


def test_storage_failure_is_not_a_missing_or_empty_collection(inspection):
    s = inspection; s.records.query.side_effect = Unavailable()
    with pytest.raises(Unavailable): scan(s)
    assert s.frames == [] and s.closed == ['vectors', 'resources']


@pytest.fixture
def standalone(inspection):
    s = inspection
    s.row['properties'] = {'created_by': 'historical-author', 'content': 'old manual text', 'id': 'display-alias',
                           'filename': 'manual.txt', 'embedding': [1.0, 0.0], 'metadata': {'custom': {'one': 1}}}
    collection = s.records.get.return_value
    s.records.get.side_effect = lambda dataset, *args, **kwargs: collection if dataset == LEGACY_VECTOR_METADATA else s.row

    async def target(lookup, *_):
        observed = client.mutate_knowledge_chunk.await_count > 0
        values = dict(lookup.model_dump(), change_epoch=4 if observed else 3)
        if observed:
            intent = client.mutate_knowledge_chunk.await_args.args[0]
            values.update(generation='a'*64, chunk=KnowledgeChunk(knowledge_id=1, chunk_id=lookup.chunk_id,
                content=intent.changes['content'], location=intent.changes['location']))
        return ChunkMutationTarget(**values)

    async def mutate(intent, *_):
        return ChunkMutationState(knowledge_id=intent.knowledge_id, chunk_id=intent.chunk_id,
            operation='create', mutation_id='a'*64, status='completed', writer_ended=True, count_delta=1, commit_epoch=4)

    client = SimpleNamespace(inspect_knowledge_chunk=AsyncMock(side_effect=target),
                             mutate_knowledge_chunk=AsyncMock(side_effect=mutate))
    migration = LegacyChunkMigration(resources=s.service.resources, vectors=s.service.vectors, client=client)
    return s, client, migration


def test_snapshot_flags_standalone_without_printing_raw_body(standalone):
    s, _, _ = standalone
    assert scan(s)['documents'] == 1
    item, = s.frames[0].documents
    assert item.standalone_candidate and 'old manual text' not in item.model_dump_json()


async def test_copy_exact_standalone_with_original_vector_and_no_file_or_model(standalone):
    s, client, migration = standalone
    result = await migration.migrate(1, s.row['document_id'], 'a'*64, '1:1', s.actor,
                                     legacy_quiesced=True, context=context())
    intent, actor, tenant = client.mutate_knowledge_chunk.await_args.args
    assert (actor, tenant) == (s.actor.user_id, s.actor.tenant_id)
    assert intent.chunk_id == s.row['document_id'] and intent.expected_change_epoch == 3 and intent.file_ref is None
    assert intent.changes['supplied_embedding'] == [1.0, 0.0] and 'embedding_model' not in intent.changes
    assert intent.changes['location'][PUBLIC_CHUNK_SOURCE_KEY] == {
        'created_by': 'historical-author', 'filename': 'manual.txt', 'id': 'display-alias',
        'metadata': {'custom': {'one': 1}},
    }
    assert result['chunk_migrated'] and result['commit_epoch'] == 4
    assert result['document_id_hash'] == hashlib.sha256(s.row['document_id'].encode()).hexdigest()
    assert client.inspect_knowledge_chunk.await_count == 2


@pytest.mark.parametrize('properties,revision', [
    ({'file_id': 'b'*32}, '1:1'), ({'metadata': {'process_source': 'UniversalImageExtractor'}}, '1:1'),
    ({'tenant_id': 'foreign'}, '1:1'), ({'index': 0}, '1:1'), ({'embedding': [1.0]}, '1:1'), ({}, '2:1'),
])
async def test_unproven_or_changed_chunks_never_reach_runtime(standalone, properties, revision):
    s, client, migration = standalone
    s.row['properties'].update(properties)
    with pytest.raises(Conflict):
        await migration.migrate(1, s.row['document_id'], 'a'*64, revision, s.actor,
                                legacy_quiesced=True, context=context())
    client.inspect_knowledge_chunk.assert_not_awaited()
    client.mutate_knowledge_chunk.assert_not_awaited()


async def test_occupied_runtime_key_is_never_overwritten(standalone):
    s, client, migration = standalone

    async def occupied(lookup, *_):
        return ChunkMutationTarget(**lookup.model_dump(), change_epoch=3, generation='b'*64,
            chunk=KnowledgeChunk(knowledge_id=1, chunk_id=lookup.chunk_id, content='newer Runtime chunk'))

    client.inspect_knowledge_chunk.side_effect = occupied
    with pytest.raises(Conflict):
        await migration.migrate(1, s.row['document_id'], 'a'*64, '1:1', s.actor,
                                legacy_quiesced=True, context=context())
    client.mutate_knowledge_chunk.assert_not_awaited()
