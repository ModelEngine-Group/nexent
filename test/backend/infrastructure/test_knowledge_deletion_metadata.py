# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DELETE-RESULT-03: scoped UTC SI timestamps preserve legacy local storage."""

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from contracts.knowledge_deletion import DELETION_KNOWLEDGE_DATASET as DATASET
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    PageRequest,
    RecordQuery,
    Revision,
    StorageScope,
)

from infrastructure.rdb.knowledge_deletion import bind_deletion_records
from infrastructure.rdb.knowledge_deletion_metadata import metadata_catalog
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def setup():
    _, table, _ = metadata_catalog()
    engine = sa.create_engine('sqlite://', execution_options={'schema_translate_map': {'nexent': None}})
    table.create(engine)
    instant = datetime(2026, 1, 1, 8, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(table.insert(), {'knowledge_id': 1, 'tenant_id': 'tenant-a', 'index_name': 'kb-one',
                                            'last_doc_update_time': instant, 'delete_flag': 'N'})
    records = bind_deletion_records(StorageScope('management', 'tenant-a', 'editor', {DATASET}), engine)
    try:
        yield records, engine, table, instant
    finally:
        records.close()
        engine.dispose()


@pytest.mark.parametrize('operator', ['eq', 'in', 'gte'])
def test_utc_query_and_legacy_wall_clock_round_trip(setup, operator):
    records, engine, table, instant = setup
    value = instant.isoformat()
    page = records.query(DATASET, RecordQuery(where=Comparison('last_doc_update_time', operator,
                         [value] if operator == 'in' else value)), PageRequest(), context=context())
    assert len(page.items) == 1 and page.items[0]['last_doc_update_time'] == value
    with engine.connect() as connection:
        stored = connection.execute(sa.select(sa.type_coerce(table.c.last_doc_update_time, sa.DateTime()))).scalar_one()
    assert stored == instant.astimezone().replace(tzinfo=None)


def test_timestamp_update_uses_revision_and_preserves_naive_local_storage(setup):
    records, engine, table, _ = setup
    instant = datetime(2026, 6, 1, 12, tzinfo=UTC)
    receipt = records.patch(DATASET, 1, FieldPatch(set_values={'last_doc_update_time': instant.isoformat()}),
                            expected=Revision('0'), context=context())
    assert receipt.matched and receipt.revision == Revision('1')
    row = records.get(DATASET, 1, context=context())
    assert row['last_doc_update_time'] == instant.isoformat() and row['updated_by'] == 'editor'
    with engine.connect() as connection:
        stored = connection.execute(sa.select(sa.type_coerce(table.c.last_doc_update_time, sa.DateTime()))).scalar_one()
    assert stored == instant.astimezone().replace(tzinfo=None)
    assert not records.patch(DATASET, 1, FieldPatch(set_values={'last_doc_update_time': instant.isoformat()}),
                             expected=Revision('0'), context=context()).matched


def test_naive_si_input_is_rejected_before_any_write(setup):
    records, _, _, _ = setup
    with pytest.raises(InvalidInput):
        records.patch(DATASET, 1, FieldPatch(set_values={'last_doc_update_time': '2026-01-01T00:00:00'}), context=context())
    assert records.get(DATASET, 1, context=context())['version'] == 0


def test_runtime_cannot_open_management_metadata(setup):
    _, engine, _, _ = setup
    with pytest.raises(ScopeDenied):
        bind_deletion_records(StorageScope('runtime', 'tenant-a', 'runtime', {DATASET}), engine)
