# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Source maintenance records cannot write or escape the selected tenant/KB."""

import pytest
from contracts.knowledge_maintenance import INSPECTION_FILES, INSPECTION_LEDGER
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    PageRequest,
    RecordQuery,
    StorageScope,
)

from infrastructure.rdb.source_inspection import bind_source_inspection_records
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_source_inspection import (
    inspection as inspection,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_source_inspection import (
    resources as resources,  # noqa: PLC0414
)


def port(s, *, knowledge_id=1):
    return bind_source_inspection_records(StorageScope('management', 'tenant-a', 'user-a',
        {INSPECTION_FILES, INSPECTION_LEDGER}), knowledge_id, s.engine)


def test_projection_filters_kb_before_caller_query_and_always_filters_tenant(inspection):
    s = inspection
    with s.engine.begin() as connection:
        connection.execute(s.tables[INSPECTION_FILES].insert(), [
            {**s.row, 'file_id': 'c'*32, 'knowledge_id': 2},
            {**s.row, 'file_id': 'd'*32, 'tenant_id': 'tenant-b'},
            {**s.row, 'file_id': 'e'*32, 'delete_flag': 'Y'}])
    records = port(s)
    try:
        result = records.query(INSPECTION_FILES, RecordQuery(), PageRequest(), context=context())
        assert [row['file_id'] for row in result.items] == ['b'*32]
        assert records.get(INSPECTION_FILES, 'c'*32, context=context()) is None
        assert records.get(INSPECTION_FILES, 'd'*32, context=context()) is None
        assert records.query(INSPECTION_FILES, RecordQuery(where=Comparison('knowledge_id', 'eq', 2)),
            PageRequest(), context=context()).items == ()
    finally: records.close()


@pytest.mark.parametrize('method', ['create', 'patch', 'delete'])
def test_all_mutations_are_denied_by_catalog(inspection, method):
    s = inspection; records = port(s)
    try:
        with pytest.raises(ScopeDenied):
            if method == 'create': records.create(INSPECTION_FILES, s.row, context=context())
            elif method == 'patch': records.patch(INSPECTION_FILES, 'b'*32, FieldPatch(set_values={'version': 2}), context=context())
            else: records.delete(INSPECTION_FILES, 'b'*32, context=context())
        assert records.get(INSPECTION_FILES, 'b'*32, context=context())['version'] == 1
    finally: records.close()


def test_inactive_ledger_is_visible_as_evidence_without_write_authority(inspection):
    s = inspection; s.update(INSPECTION_LEDGER, status='DELETED', delete_flag='Y')
    records = port(s)
    try:
        row = records.get(INSPECTION_LEDGER, 1, context=context())
        assert row['status'] == 'DELETED' and row['delete_flag'] == 'Y'
    finally: records.close()


@pytest.mark.parametrize('knowledge_id', [0, -1, True, '1'])
def test_selected_kb_is_mandatory_and_typed(inspection, knowledge_id):
    with pytest.raises(InvalidInput): port(inspection, knowledge_id=knowledge_id)


def test_runtime_and_broad_system_handles_are_rejected(inspection):
    for scope in (StorageScope('runtime', 'tenant-a', 'user-a', {INSPECTION_FILES, INSPECTION_LEDGER}),
        StorageScope('management', None, 'operator', {INSPECTION_FILES, INSPECTION_LEDGER}, system=True)):
        with pytest.raises(ScopeDenied): bind_source_inspection_records(scope, 1, inspection.engine)
