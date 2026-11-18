# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Current Management DAC surrounds redacted legacy vector evidence."""

import hashlib
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from management.services.knowledge_base.legacy_vectors import LegacyVectorInspector
from nexent.storage.errors import Conflict, ScopeDenied, Unavailable
from nexent.storage.models import Page, StorageScope

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import cleanse_resources
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def inspection(resources):
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
