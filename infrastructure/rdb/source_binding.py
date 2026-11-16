# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted, audited CAS mapping for binding preallocated upload sources."""

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

DATASET = "knowledge_source_bindings"


def source_catalog():
    table = KnowledgeFileLifecycle.__table__
    names = [
        "file_id",
        "tenant_id",
        "knowledge_id",
        "index_name",
        "storage_object_id",
        "uploaded_at",
        "created_by",
        "updated_by",
        "create_time",
        "update_time",
        "delete_flag",
        "status",
        "stage",
        "file_size",
        "bucket_name",
        "object_name",
        "source_upload_sha256",
        "source_upload_started_at",
        "source_reconcile_after",
        "upload_owner_service",
        "error_code",
        "error_stage",
        "source_generation",
        "source_space",
        "source_key",
        "source_revision",
        "source_sha256",
        "version",
    ]
    fields = tuple(
        FieldDefinition(
            name,
            "integer"
            if name
            in {
                "knowledge_id",
                "source_generation",
                "version",
                "file_size",
                "storage_object_id",
            }
            else "string",
            nullable=table.c[name].nullable,
        )
        for name in names
    )
    definition = DatasetDefinition(
        DATASET,
        "file_id",
        fields,
        frozenset({"management"}),
        frozenset({"management"}),
        tenant_field="tenant_id",
        active_field="delete_flag",
    )
    audit = RecordAudit(
        "create_time",
        "update_time",
        "created_by",
        "updated_by",
        extra_dates=frozenset(
            {"source_upload_started_at", "source_reconcile_after", "uploaded_at"}
        ),
    )
    return definition, table, audit


def bind_source_records(scope, engine):
    definition, table, audit = source_catalog()
    return SQLRecordStore(
        scope,
        DatasetCatalog((definition,)),
        {DATASET: table},
        engine,
        revision_fields={DATASET: "version"},
        audit_mappings={DATASET: audit},
    )
