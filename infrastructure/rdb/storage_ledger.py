# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Audited ledger writes, scoped history and finite cross-tenant ownership grants."""

from dataclasses import replace

from contracts.knowledge import (
    STORAGE_LEDGER_DATASET as LEDGER,
)
from contracts.knowledge import (
    STORAGE_LEDGER_HISTORY_DATASET as HISTORY,
)
from contracts.knowledge import (
    STORAGE_LEDGER_OWNER_DATASET as LOOKUP,
)
from nexent.storage.errors import InvalidInput
from nexent.storage.models import StorageScope
from sqlalchemy import select

from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


def ledger_catalog():
    table = KnowledgeStorageObject.__table__
    integer_fields = {"storage_object_id", "knowledge_id", "raw_bytes", "version"}
    fields = tuple(
        FieldDefinition(
            column.name,
            "integer" if column.name in integer_fields else "string",
            nullable=column.nullable,
        )
        for column in table.columns
    )
    definition = DatasetDefinition(
        LEDGER,
        "storage_object_id",
        fields,
        frozenset({"management"}),
        frozenset({"management"}),
        tenant_field="tenant_id",
        active_field="delete_flag",
    )
    return (
        definition,
        table,
        RecordAudit("create_time", "update_time", "created_by", "updated_by"),
    )


def bind_ledger_records(scope, engine):
    ledger, table, audit = ledger_catalog()
    history = replace(ledger, name=HISTORY, write_roles=frozenset(), active_field=None)
    return SQLRecordStore(
        scope,
        DatasetCatalog((ledger, history)),
        {LEDGER: table, HISTORY: table},
        engine,
        revision_fields={LEDGER: "version"},
        audit_mappings={LEDGER: audit, HISTORY: audit},
    )


def bind_ledger_lookup(bucket, key, engine, *, include_deleted=False):
    if (
        type(include_deleted) is not bool
        or not isinstance(bucket, str)
        or not 0 < len(bucket) <= 255
        or not isinstance(key, str)
        or not 0 < len(key) <= 1024
    ):
        raise InvalidInput()
    definition, table, audit = ledger_catalog()
    query = select(table).where(
        table.c.bucket_name == bucket, table.c.object_name == key
    )
    if not include_deleted:
        query = query.where(table.c.status == "COMMITTED")
    lookup = replace(
        definition,
        name=LOOKUP,
        write_roles=frozenset(),
        allow_system=True,
        active_field=None if include_deleted else "delete_flag",
    )
    return SQLRecordStore(
        StorageScope("management", None, "storage-ownership", {LOOKUP}, system=True),
        DatasetCatalog((lookup,)),
        {LOOKUP: query.subquery(LOOKUP)},
        engine,
        revision_fields={},
        audit_mappings={LOOKUP: audit},
    )
