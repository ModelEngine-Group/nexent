# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SU tenant deletion unlinks DataMate metadata without touching remote objects."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.knowledge import STORAGE_LEDGER_DATASET as LEDGER
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
from management.services.knowledge_base import external_unlink as service
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import FieldPatch, StorageScope

from infrastructure.rdb import knowledge_base_metadata as mapping
from infrastructure.rdb import storage_ledger
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_base_metadata import (
    admission,  # noqa: F401
    metadata,  # noqa: F401
    resources,  # noqa: F401
    sqlite_threads,  # noqa: F401
)


@pytest.fixture
def external(metadata, monkeypatch):  # noqa: F811
    m, s = metadata, metadata.s
    s.records.patch(KB, 1, FieldPatch(set_values={'knowledge_sources': 'datamate', 'ingroup_permission': None,
                                                'deletion_request': None}), context=context())
    s.update('cleanse_knowledge', knowledge_sources='datamate', ingroup_permission=None, deletion_request=None)
    schema = sa.MetaData()
    ledger = sa.Table('external_ledger', schema,
        *(sa.Column(name, sa.Integer, primary_key=name == 'storage_object_id')
          for name in ('storage_object_id', 'knowledge_id', 'version')),
        *(sa.Column(name, sa.String) for name in ('tenant_id', 'status', 'delete_flag', 'created_by', 'updated_by')),
        sa.Column('create_time', sa.DateTime), sa.Column('update_time', sa.DateTime))
    schema.create_all(s.engine)
    monkeypatch.setattr(storage_ledger, 'KnowledgeStorageObject', SimpleNamespace(__table__=ledger))
    records = mapping.bind_base_metadata_records(StorageScope('management', 'tenant-a', 'user-a', {
        KB, FILES, TOOLS, CONVERSATIONS, TAGS, PROJECTIONS, LEDGER}), s.engine)
    issuer = Mock(return_value='operator-tenant')
    monkeypatch.setattr(service, 'require_tenant_cleanup_issuer', issuer)
    try:
        yield SimpleNamespace(**locals())
    finally:
        records.close()


def unlink(e):
    return service.unlink_datamate_record(e.records, e.s.authorized, 1, e.s.actor, context=context())


def test_only_local_catalog_and_bindings_are_removed_in_one_transaction(external):
    e = external
    result = unlink(e)
    assert result['knowledge_records_deleted'] == 1
    assert e.records.get(KB, 1, context=context()) is None
    with e.s.engine.connect() as conn:
        saved = conn.execute(sa.select(e.s.knowledge)).mappings().one()
    assert saved['delete_flag'] == 'Y' and saved['updated_by'] == 'user-a' and saved['created_by'] == 'user-a'
    assert saved['deletion_request'] is None
    assert [r['params']['index_names'] for r in e.m.rows('tools')][:2] == [['other'], ['other']]
    assert e.m.rows('conversations')[0]['knowledge_scope']['local']['knowledge_ids'] == ['2']
    assert e.m.rows('conversations')[0]['knowledge_scope']['aidp']['kds_ids'] == ['cloud']
    assert [r['projection_id'] for r in e.m.rows('projections')] == [2, 3, 4]
    assert e.issuer.call_count == 2


@pytest.mark.parametrize('changes', [{'tenant_id': 'foreign'}, {'knowledge_sources': 'elasticsearch'},
                                    {'deletion_request': {'phase': 'files'}}])
def test_non_datamate_wrong_tenant_or_existing_intent_is_preserved(external, changes):
    e = external
    with e.s.engine.begin() as conn:
        conn.execute(e.s.knowledge.update().values(**changes))
    with pytest.raises((ScopeDenied, Conflict)):
        unlink(e)
    assert all(row['delete_flag'] == 'N' for row in e.m.rows('tags'))


def test_non_su_or_revoked_actor_cannot_unlink_metadata(external):
    external.issuer.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        unlink(external)
    assert external.records.get(KB, 1, context=context()) is not None


@pytest.mark.parametrize('obligation', ['file', 'ledger'])
def test_local_cleanup_obligations_must_not_be_orphaned(external, obligation):
    e = external
    if obligation == 'ledger':
        with e.s.engine.begin() as conn:
            conn.execute(e.ledger.insert(), {'storage_object_id': 1, 'knowledge_id': 1, 'tenant_id': 'tenant-a',
                                             'status': 'COMMITTED', 'delete_flag': 'N', 'version': 0})
    else:
        values = {k: v for k, v in e.s.spec().items() if k != 'created_by'}
        e.s.records.create(FILES, {**values, 'status': 'UPLOADED', 'stage': 'UPLOAD',
                                   'source_generation': 0, 'processing_attempt': 0}, context=context())
    with pytest.raises(Conflict):
        unlink(e)
    assert e.records.get(KB, 1, context=context()) is not None


def test_failure_after_binding_updates_rolls_back_everything(external, monkeypatch):
    e = external
    original = type(e.records).delete

    def fail_last(self, dataset, *args, **kwargs):
        if dataset == KB:
            raise Conflict()
        return original(self, dataset, *args, **kwargs)

    monkeypatch.setattr(type(e.records), 'delete', fail_last)
    before = e.records.get(KB, 1, context=context())
    with pytest.raises(Conflict):
        unlink(e)
    assert e.records.get(KB, 1, context=context()) == before
    assert all(row['delete_flag'] == 'N' for row in e.m.rows('tags'))
    assert all(row['params']['index_names'] == ['kb-one', 'other'] for row in e.m.rows('tools'))


def test_ledger_access_is_read_only_in_metadata_port(external):
    with pytest.raises(ScopeDenied):
        external.records.delete(LEDGER, 1, context=context())


def test_revoked_su_at_final_check_rolls_back_bindings(external):
    e = external
    e.issuer.side_effect = ['operator', ScopeDenied()]
    with pytest.raises(ScopeDenied):
        unlink(e)
    assert e.records.get(KB, 1, context=context()) is not None
    assert all(row['delete_flag'] == 'N' for row in e.m.rows('tags'))
