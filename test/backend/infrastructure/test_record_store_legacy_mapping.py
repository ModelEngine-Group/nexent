# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-INFRA-DPR-LEGACY-01/02: scoped existing tables without invented revisions."""

import pytest
import sqlalchemy as sa
from nexent.storage.errors import CapabilityUnsupported, InvalidInput, ScopeDenied
from nexent.storage.models import (
    FieldPatch,
    PageRequest,
    RecordQuery,
    Revision,
    StorageScope,
)

from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)
from test.backend.infrastructure.test_record_store import context


@pytest.fixture
def legacy():
    engine = sa.create_engine('sqlite://')
    metadata = sa.MetaData()
    table = sa.Table('legacy', metadata,
                     sa.Column('id', sa.Integer, primary_key=True),
                     sa.Column('version_no', sa.Integer, primary_key=True),
                     sa.Column('owner_tenant', sa.String), sa.Column('payload', sa.JSON),
                     sa.Column('delete_flag', sa.String),
                     *(sa.Column(name, sa.DateTime) for name in ('create_time', 'update_time')),
                     *(sa.Column(name, sa.String) for name in ('created_by', 'updated_by')))
    metadata.create_all(engine)
    projection = sa.select(*table.c, table.c.owner_tenant.label('tenant_id')).subquery()
    fields = tuple(FieldDefinition(c.name, 'integer' if isinstance(c.type, sa.Integer)
                                  else 'object' if isinstance(c.type, sa.JSON) else 'string', nullable=c.nullable)
                   for c in projection.c)
    definition = DatasetDefinition('legacy', 'id', fields, frozenset({'management'}), frozenset({'management'}),
                                   tenant_field='tenant_id', active_field='delete_flag')
    catalog = DatasetCatalog((definition,))
    audit = RecordAudit('create_time', 'update_time', 'created_by', 'updated_by')
    with engine.begin() as connection:
        connection.execute(table.insert(), [{'id': i, 'version_no': v, 'owner_tenant': t,
                                                'payload': {'keep': v}, 'delete_flag': 'N', 'created_by': 'original'}
                                             for i, v, t in ((1, 0, 'a'), (1, 1, 'a'), (2, 0, 'b'))])
    store = SQLRecordStore(StorageScope('management', 'a', 'editor', {'legacy'}), catalog,
                           {'legacy': projection}, engine, revision_fields={'legacy': None},
                           audit_mappings={'legacy': audit}, write_tables={'legacy': table})
    try:
        yield store, engine, table
    finally:
        store.close()
        engine.dispose()


def test_tuple_key_updates_exact_version_and_current_audit(legacy):
    store, _, _ = legacy
    with store.transaction(context=context()) as transaction:
        receipt = transaction.patch('legacy', (1, 1), FieldPatch(set_values={'payload': {'keep': 1, 'new': True}}), context=context())
        assert receipt.matched and receipt.revision is None
        row = transaction.get('legacy', (1, 1), context=context())
        assert row['created_by'] == 'original' and row['updated_by'] == 'editor'
        assert row['update_time']
    assert store.get('legacy', (1, 0), context=context())['payload'] == {'keep': 0}
    assert store.get('legacy', (1, 1), context=context())['payload'] == {'keep': 1, 'new': True}


@pytest.mark.parametrize('key', [1, (1,), (1, 0, 2), (True, 0)])
def test_partial_or_ambiguous_keys_are_rejected(legacy, key):
    store, _, _ = legacy
    with pytest.raises(InvalidInput):
        store.get('legacy', key, context=context())


def test_revisionless_writes_require_explicit_transaction_and_never_fake_cas(legacy):
    store, _, _ = legacy
    with pytest.raises(CapabilityUnsupported):
        store.patch('legacy', (1, 0), FieldPatch(set_values={}), context=context())
    with store.transaction(context=context()) as transaction:
        with pytest.raises(CapabilityUnsupported):
            transaction.patch('legacy', (1, 0), FieldPatch(set_values={}), expected=Revision('1'), context=context())
        with pytest.raises(CapabilityUnsupported):
            transaction.delete('legacy', (1, 0), expected=Revision('1'), context=context())


@pytest.mark.parametrize('field,value', [('version_no', 3), ('tenant_id', 'b')])
def test_key_and_virtual_scope_fields_cannot_be_written(legacy, field, value):
    store, _, _ = legacy
    with store.transaction(context=context()) as transaction, pytest.raises(ScopeDenied):
        transaction.patch('legacy', (1, 0), FieldPatch(set_values={field: value}), context=context())


def test_projection_restricts_writes_and_soft_delete_preserves_foreign_row(legacy):
    store, engine, table = legacy
    with store.transaction(context=context()) as transaction:
        assert not transaction.patch('legacy', (2, 0), FieldPatch(set_values={}), context=context()).matched
        assert not transaction.delete('legacy', (2, 0), context=context()).deleted
        assert transaction.delete('legacy', (1, 1), context=context()).deleted
    assert store.get('legacy', (1, 1), context=context()) is None
    with engine.connect() as connection:
        rows = connection.execute(sa.select(table).order_by(table.c.id, table.c.version_no)).mappings().all()
    assert [row['delete_flag'] for row in rows] == ['N', 'Y', 'N']
    assert rows[1]['updated_by'] == 'editor'


def test_error_rolls_back_merged_payload_and_soft_delete(legacy):
    store, _, _ = legacy
    with pytest.raises(ValueError), store.transaction(context=context()) as transaction:
        transaction.patch('legacy', (1, 0), FieldPatch(set_values={'payload': {}}), context=context())
        transaction.delete('legacy', (1, 1), context=context())
        raise ValueError('controlled failure')
    assert store.get('legacy', (1, 0), context=context())['payload'] == {'keep': 0}
    assert store.get('legacy', (1, 1), context=context()) is not None


def test_composite_paging_includes_every_key_and_view_create_is_unsupported(legacy):
    store, _, _ = legacy
    first = store.query('legacy', RecordQuery(), PageRequest(limit=1), context=context())
    second = store.query('legacy', RecordQuery(), PageRequest(limit=1, cursor=first.next_cursor), context=context())
    assert [(row['id'], row['version_no']) for row in (*first.items, *second.items)] == [(1, 0), (1, 1)]
    with store.transaction(context=context()) as transaction, pytest.raises(CapabilityUnsupported):
        transaction.create('legacy', {'id': 3, 'version_no': 0}, context=context())
