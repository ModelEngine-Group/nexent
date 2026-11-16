# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant-scoped source and storage-ledger records in one local transaction domain."""

from infrastructure.rdb.knowledge_storage_record import KnowledgeStorageObject
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.source_binding import DATASET as SOURCE
from infrastructure.rdb.source_binding import source_catalog
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

LEDGER = "knowledge_storage_objects"


def bind_upload_records(scope, engine):
    source, source_table, source_audit = source_catalog()
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
    ledger = DatasetDefinition(
        LEDGER,
        "storage_object_id",
        fields,
        frozenset({"management"}),
        frozenset({"management"}),
        tenant_field="tenant_id",
        active_field="delete_flag",
    )
    return SQLRecordStore(
        scope,
        DatasetCatalog((source, ledger)),
        {SOURCE: source_table, LEDGER: table},
        engine,
        revision_fields={SOURCE: "version", LEDGER: "version"},
        audit_mappings={
            SOURCE: source_audit,
            LEDGER: RecordAudit(
                "create_time", "update_time", "created_by", "updated_by"
            ),
        },
    )
