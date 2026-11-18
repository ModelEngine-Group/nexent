# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only legacy source evidence retains actual DAC and exact object ownership."""

import hashlib
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.knowledge_maintenance import INSPECTION_FILES, INSPECTION_LEDGER
from management.services.knowledge_base.source_inspection import (
    KnowledgeSourceInspector,
)
from nexent.storage.errors import Conflict, NotFound, ScopeDenied, Unavailable
from nexent.storage.models import ObjectMetadata, ObjectRef, Revision, StorageScope

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import cleanse_resources
from infrastructure.rdb import source_inspection as mapping
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def inspection(resources, monkeypatch):
    _, update_resource, engine, _ = resources
    metadata = sa.MetaData()
    tables = {}
    for name, original, names, key in [(INSPECTION_FILES, mapping.files, mapping.FILE_FIELDS, 'file_id'),
                                      (INSPECTION_LEDGER, mapping.ledger, mapping.LEDGER_FIELDS, 'storage_object_id')]:
        tables[name] = sa.Table(name, metadata, *[sa.Column(field, original.c[field].type,
            primary_key=field == key, nullable=field != key) for field in names])
    metadata.create_all(engine)
    monkeypatch.setattr(mapping, 'files', tables[INSPECTION_FILES])
    monkeypatch.setattr(mapping, 'ledger', tables[INSPECTION_LEDGER])
    data = b'actual independent content'
    digest = hashlib.sha256(data).hexdigest()
    row = {'file_id': 'b'*32, 'tenant_id': 'tenant-a', 'knowledge_id': 1, 'index_name': 'kb-one',
        'bucket_name': 'bucket', 'object_name': 'tenant-a/source.txt', 'source_space': 'files', 'source_key': 'tenant-a/source.txt',
        'source_revision': 'etag:one', 'source_sha256': digest, 'source_generation': 0, 'version': 1, 'storage_object_id': 1,
        'file_size': len(data), 'status': 'COMPLETED', 'delete_flag': 'N'}
    stored = {'storage_object_id': 1, 'tenant_id': 'tenant-a', 'knowledge_id': 1, 'index_name': 'kb-one',
        'bucket_name': 'bucket', 'object_name': 'tenant-a/source.txt', 'raw_bytes': len(data), 'status': 'COMMITTED', 'delete_flag': 'N', 'version': 1}
    with engine.begin() as connection:
        connection.execute(tables[INSPECTION_FILES].insert(), row)
        connection.execute(tables[INSPECTION_LEDGER].insert(), stored)
    ports_closed, object_closed, streams_closed, readers = [], [], [], []

    @contextmanager
    def ports(actor, knowledge_id, *, context):
        records = mapping.bind_source_inspection_records(StorageScope('management', actor.tenant_id, actor.user_id,
            {INSPECTION_FILES, INSPECTION_LEDGER}), knowledge_id, engine)
        resources_port = cleanse_resources.bind_cleanse_resources(StorageScope('management', actor.tenant_id, actor.user_id,
            set(cleanse_resources.TABLES)), engine)
        try: yield records, resources_port
        finally: records.close(); resources_port.close(); ports_closed.append(True)

    objects = Mock(scope=StorageScope('management', 'tenant-a', 'user-a', {'files'}))
    objects.stat.return_value = ObjectMetadata(ObjectRef('files', row['object_name'], Revision('etag:one')), len(data), 'text/plain')

    @contextmanager
    def open_read(ref, *, context):
        stream = BytesIO(data); readers.append(ref)
        try: yield stream
        finally: stream.close(); streams_closed.append(stream.closed)
    objects.open_read.side_effect = open_read
    objects.close.side_effect = lambda: object_closed.append(True)
    factory = Mock(return_value=objects)

    def update(dataset=INSPECTION_FILES, **values):
        with engine.begin() as connection: connection.execute(tables[dataset].update().values(**values))
    return SimpleNamespace(service=KnowledgeSourceInspector(bucket='bucket', max_bytes=1000, ports=ports, objects=factory),
        actor=ServicePrincipal('user-a', 'tenant-a'), row=row, stored=stored, update=update,
        update_resource=update_resource, objects=objects, factory=factory, data=data, digest=digest,
        ports_closed=ports_closed, object_closed=object_closed, streams_closed=streams_closed, readers=readers,
        tables=tables, engine=engine)


def inspect(s, **kwargs):
    return s.service.page(1, s.actor, context=context(), **kwargs)


def test_explicit_file_filter_does_not_read_other_file_sources(inspection):
    s=inspection
    page=inspect(s,file_id=s.row['file_id'])
    assert [item.file_id for item in page.files]==[s.row['file_id']]
    before=s.factory.call_count
    assert not inspect(s,file_id='not-an-existing-id').files
    assert s.factory.call_count==before


def test_reads_fixed_revision_hashes_actual_bytes_and_never_grants_migration(inspection):
    s = inspection
    report = inspect(s)
    item, = report.files
    assert item.issues == [] and item.candidate_source.sha256 == s.digest
    assert item.candidate_source.version == 'etag:one' and item.observed_size == len(s.data)
    assert report.actor_id == 'user-a' and report.tenant_id == 'tenant-a'
    assert set(report.pending_checks) == {'legacy_vectors', 'legacy_tasks', 'runtime_visibility', 'model_dimensions'}
    assert s.readers == [ObjectRef('files', s.row['object_name'], Revision('etag:one'))]
    s.factory.assert_called_once_with('tenant-a', 'user-a', s.row['object_name'], 'bucket', writable=False)
    assert s.ports_closed == [True] and s.object_closed == [True] and s.streams_closed == [True]
    s.objects.put.assert_not_called(); s.objects.delete.assert_not_called()


@pytest.mark.parametrize('change', ['membership', 'private', 'deleting'])
def test_actual_current_authorization_is_required_before_object_reads(inspection, change):
    s = inspection
    if change == 'membership': s.update_resource('cleanse_memberships', delete_flag='Y')
    elif change == 'private': s.update_resource('cleanse_knowledge', created_by='other', ingroup_permission='PRIVATE')
    else: s.update_resource('cleanse_knowledge', deletion_request={'pending': True})
    with pytest.raises(ScopeDenied): inspect(s)
    s.factory.assert_not_called()


@pytest.mark.parametrize('change,code', [
    ({'file_id': 'old-file-id'}, 'FILE_ID_NONCANONICAL'),
    ({'file_id': ''}, 'FILE_ID_NONCANONICAL'),
    ({'source_revision': None}, 'SOURCE_REVISION_UNPINNED'),
    ({'source_sha256': None}, 'SOURCE_HASH_UNPINNED'),
    ({'source_space': None}, 'SOURCE_SPACE_UNPINNED'),
    ({'source_key': None}, 'SOURCE_KEY_UNPINNED'),
    ({'storage_object_id': None}, 'LEDGER_LINK_UNBOUND'),
    ({'file_size': None}, 'SOURCE_SIZE_UNPINNED'),
    ({'source_generation': None}, 'SOURCE_GENERATION_UNKNOWN'),
    ({'source_sha256': '0'*64}, 'SOURCE_HASH_MISMATCH'),
    ({'status': 'PROCESSING', 'process_task_id': 'old-task'}, 'LEGACY_TASK_UNVERIFIED'),
    ({'deletion_request': {'pending': True}}, 'DELETION_PENDING'),
])
def test_legacy_gaps_are_reported_without_inventing_identity_or_rewriting_pg(inspection, change, code):
    s = inspection; s.update(**change)
    report = inspect(s)
    assert code in report.files[0].issues
    with s.engine.connect() as connection:
        actual = connection.execute(sa.select(s.tables[INSPECTION_FILES])).mappings().one()
        assert all(actual[key] == value for key, value in change.items()) and actual['version'] == 1


@pytest.mark.parametrize('change,code', [
    ({'bucket_name': 'other'}, 'SOURCE_BUCKET_UNSUPPORTED'),
    ({'object_name': 'http://secret:password@host/f?q=token', 'source_key': None}, 'SOURCE_ALIAS_UNRESOLVED'),
    ({'source_key': 'other-key'}, 'SOURCE_KEY_CONFLICT'),
    ({'storage_object_id': 2}, 'LEDGER_LINK_MISMATCH'),
])
def test_ambiguous_source_is_not_opened_or_leaked(inspection, change, code):
    s = inspection; s.update(**change)
    report = inspect(s)
    assert code in report.files[0].issues and report.files[0].candidate_source is None
    assert 'password' not in report.model_dump_json() and 'token' not in report.model_dump_json()
    s.factory.assert_not_called()


@pytest.mark.parametrize('change,code', [({'tenant_id': 'tenant-b'}, 'LEDGER_UNPROVEN'),
    ({'knowledge_id': 2}, 'LEDGER_UNPROVEN'), ({'status': 'DELETED'}, 'LEDGER_INACTIVE')])
def test_foreign_or_inactive_ledger_never_authorizes_object_reads(inspection, change, code):
    s = inspection; s.update(INSPECTION_LEDGER, **change)
    item, = inspect(s).files
    assert code in item.issues and item.candidate_source is None
    s.factory.assert_not_called()


def test_object_missing_is_reported_but_storage_failure_is_not_disguised(inspection):
    s = inspection
    s.objects.stat.side_effect = NotFound()
    assert 'SOURCE_MISSING' in inspect(s).files[0].issues
    s.objects.stat.side_effect = Unavailable()
    with pytest.raises(Unavailable): inspect(s)
    assert s.object_closed == [True, True] and len(s.ports_closed) == 2


@pytest.mark.parametrize('change', ['file', 'permission', 'ledger'])
def test_change_during_object_read_discards_entire_page(inspection, change):
    s = inspection
    original = s.objects.open_read.side_effect
    @contextmanager
    def changed(ref, *, context):
        with original(ref, context=context) as stream: yield stream
        if change == 'file': s.update(version=2)
        elif change == 'permission': s.update_resource('cleanse_memberships', delete_flag='Y')
        else: s.update(INSPECTION_LEDGER, raw_bytes=100)
    s.objects.open_read.side_effect = changed
    with pytest.raises((Conflict, ScopeDenied)): inspect(s)
    assert s.streams_closed == [True] and s.object_closed == [True] and s.ports_closed == [True]


@pytest.mark.parametrize('size,code', [(-1, 'SOURCE_METADATA_INVALID'), (1001, 'SOURCE_TOO_LARGE'), (27, 'SOURCE_SIZE_MISMATCH')])
def test_invalid_oversized_or_incomplete_object_is_not_treated_as_valid(inspection, size, code):
    s = inspection; metadata = s.objects.stat.return_value
    s.objects.stat.return_value = ObjectMetadata(metadata.ref, size, 'text/plain')
    assert code in inspect(s).files[0].issues
    if size in {-1, 1001}: assert s.readers == []
    assert s.object_closed == [True]


def test_metadata_hash_is_checked_against_independently_read_bytes(inspection):
    s = inspection; metadata = s.objects.stat.return_value
    s.objects.stat.return_value = ObjectMetadata(metadata.ref, len(s.data), 'text/plain', sha256='f'*64)
    item, = inspect(s).files
    assert 'SOURCE_HASH_MISMATCH' in item.issues and item.candidate_source.sha256 == s.digest


def test_foreign_object_handle_is_closed_and_rejected(inspection):
    s = inspection; s.objects.scope = StorageScope('management', 'tenant-b', 'user-a', {'files'})
    with pytest.raises(ScopeDenied): inspect(s)
    s.objects.stat.assert_not_called()
    assert s.object_closed == [True]


def test_local_only_alias_is_reported_without_filesystem_access_or_path_export(inspection):
    s = inspection; s.update(source_key=None, object_name=None, local_source_path='C:/private/secret.txt')
    report = inspect(s)
    assert 'LOCAL_SOURCE_UNBOUND' in report.files[0].issues and 'private' not in report.model_dump_json()
    s.factory.assert_not_called()


def test_report_cannot_remove_unfinished_migration_checks(inspection):
    from pydantic import ValidationError

    report = inspect(inspection)
    data = report.model_dump()
    data['pending_checks'] = ()
    with pytest.raises(ValidationError): type(report).model_validate(data)
