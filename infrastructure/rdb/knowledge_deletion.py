# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant-scoped deletion journal reuses the existing lifecycle CAS and audit fields."""

from dataclasses import replace

from contracts.knowledge import STORAGE_LEDGER_HISTORY_DATASET as HISTORY
from contracts.knowledge_deletion import DELETION_DATASET
from nexent.storage.errors import ScopeDenied

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.storage_ledger import ledger_catalog
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

files = KnowledgeFileLifecycle.__table__


def deletion_catalog():
    names = (
        "file_id", "tenant_id", "knowledge_id", "index_name", "original_filename",
        "object_name", "status", "stage", "source_generation", "source_space",
        "source_key", "source_revision", "source_sha256", "deletion_request",
        "version", "deleted_at", "created_by", "updated_by", "create_time", "update_time",
        "delete_flag", "bucket_name", "file_size", "storage_object_id", "uploaded_at",
        "upload_owner_service", "source_upload_sha256", "error_code",
    )
    integers = {"knowledge_id", "source_generation", "version", "file_size", "storage_object_id"}
    definition = DatasetDefinition(
        DELETION_DATASET,
        "file_id",
        tuple(FieldDefinition(
            name, "object" if name == "deletion_request" else "integer" if name in integers else "string",
            nullable=files.c[name].nullable,
        ) for name in names),
        frozenset({"management"}), frozenset({"management"}), tenant_field="tenant_id",
    )
    return definition, files


def bind_deletion_records(scope, engine):
    definition, table = deletion_catalog()
    ledger, ledger_table, ledger_audit = ledger_catalog()
    history = replace(ledger, name=HISTORY, write_roles=frozenset(), active_field=None)
    tables = {DELETION_DATASET: table, ledger.name: ledger_table, HISTORY: ledger_table}
    if not scope.namespaces <= tables.keys():
        raise ScopeDenied()
    return SQLRecordStore(
        scope, DatasetCatalog((definition, ledger, history)),
        {name: tables[name] for name in scope.namespaces}, engine,
        revision_fields={DELETION_DATASET: "version", ledger.name: "version"},
        audit_mappings={DELETION_DATASET: RecordAudit(
            "create_time", "update_time", "created_by", "updated_by",
            extra_dates=frozenset({"deleted_at", "uploaded_at"}),
        ), ledger.name: ledger_audit, HISTORY: ledger_audit},
    )
