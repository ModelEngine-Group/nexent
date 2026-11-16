# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ledger history and exact-object discovery retain independent read grants."""

import pytest
import sqlalchemy as sa
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import FieldPatch, PageRequest, RecordQuery, StorageScope

from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject
from infrastructure.rdb.storage_ledger import (
    HISTORY,
    LEDGER,
    LOOKUP,
    bind_ledger_lookup,
    bind_ledger_records,
)
from test.backend.infrastructure.test_record_store import context


@pytest.fixture
def ledger_engine():
    engine = sa.create_engine(
        "sqlite://", execution_options={"schema_translate_map": {"nexent": None}}
    )
    table = KnowledgeStorageObject.__table__
    table.create(engine)
    with engine.begin() as conn:
        conn.execute(
            table.insert(),
            [
                {
                    "storage_object_id": 1,
                    "tenant_id": "tenant-a",
                    "knowledge_id": 7,
                    "index_name": "kb",
                    "bucket_name": "files",
                    "object_name": "one.txt",
                    "raw_bytes": 6,
                    "status": "COMMITTED",
                    "delete_flag": "N",
                    "version": 0,
                },
                {
                    "storage_object_id": 2,
                    "tenant_id": "tenant-b",
                    "knowledge_id": 8,
                    "index_name": "other",
                    "bucket_name": "files",
                    "object_name": "two.txt",
                    "raw_bytes": 900,
                    "status": "COMMITTED",
                    "delete_flag": "N",
                    "version": 0,
                },
                {
                    "storage_object_id": 3,
                    "tenant_id": "tenant-a",
                    "knowledge_id": 7,
                    "index_name": "kb",
                    "bucket_name": "files",
                    "object_name": "deleted.txt",
                    "raw_bytes": 4,
                    "status": "DELETED",
                    "delete_flag": "Y",
                    "version": 0,
                },
            ],
        )
    yield engine
    engine.dispose()


def test_history_is_explicit_readonly_and_tenant_scoped(ledger_engine):
    store = bind_ledger_records(
        StorageScope("management", "tenant-a", "user-a", {LEDGER, HISTORY}),
        ledger_engine,
    )
    try:
        assert store.get(LEDGER, 3, context=context()) is None
        assert store.get(HISTORY, 3, context=context())["status"] == "DELETED"
        assert store.get(HISTORY, 2, context=context()) is None
        with pytest.raises(ScopeDenied):
            store.patch(
                HISTORY,
                3,
                FieldPatch(set_values={"status": "COMMITTED"}),
                context=context(),
            )
    finally:
        store.close()


def test_system_lookup_is_bound_to_one_object_and_cannot_write(ledger_engine):
    store = bind_ledger_lookup("files", "two.txt", ledger_engine)
    try:
        assert store.scope.system and store.scope.tenant_id is None
        page = store.query(LOOKUP, RecordQuery(), PageRequest(), context=context())
        assert [row["tenant_id"] for row in page.items] == ["tenant-b"]
        assert store.get(LOOKUP, 1, context=context()) is None
        with pytest.raises(ScopeDenied):
            store.delete(LOOKUP, 2, context=context())
    finally:
        store.close()


@pytest.mark.parametrize("include_deleted,count", [(False, 0), (True, 1)])
def test_system_history_lookup_requires_explicit_flag(
    ledger_engine, include_deleted, count
):
    store = bind_ledger_lookup(
        "files", "deleted.txt", ledger_engine, include_deleted=include_deleted
    )
    try:
        assert (
            len(
                store.query(
                    LOOKUP, RecordQuery(), PageRequest(), context=context()
                ).items
            )
            == count
        )
    finally:
        store.close()
