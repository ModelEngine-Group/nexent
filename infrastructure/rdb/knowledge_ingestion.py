# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restricted lifecycle records for Management's persistent ingestion coordinator."""

from contracts.knowledge_ingestion import INGESTION_DATASET

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

files = KnowledgeFileLifecycle.__table__


def ingestion_catalog():
    names = (
        "file_id",
        "tenant_id",
        "knowledge_id",
        "index_name",
        "original_filename",
        "bucket_name",
        "object_name",
        "status",
        "stage",
        "source_generation",
        "source_space",
        "source_key",
        "source_revision",
        "source_sha256",
        "ingestion_request",
        "processing_attempt",
        "process_task_id",
        "forward_task_id",
        "parent_task_id",
        "version",
        "error_code",
        "error_message",
        "error_stage",
        "completed_at",
        "failed_at",
        "created_by",
        "updated_by",
        "create_time",
        "update_time",
        "delete_flag",
    )
    integers = {"knowledge_id", "source_generation", "processing_attempt", "version"}
    fields = tuple(
        FieldDefinition(
            name,
            "object"
            if name == "ingestion_request"
            else "integer"
            if name in integers
            else "string",
            nullable=files.c[name].nullable,
        )
        for name in names
    )
    definition = DatasetDefinition(
        INGESTION_DATASET,
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
        extra_dates=frozenset({"completed_at", "failed_at"}),
    )
    return definition, files, audit


def bind_ingestion_records(scope, engine):
    definition, table, audit = ingestion_catalog()
    return SQLRecordStore(
        scope,
        DatasetCatalog((definition,)),
        {INGESTION_DATASET: table},
        engine,
        revision_fields={INGESTION_DATASET: "version"},
        audit_mappings={INGESTION_DATASET: audit},
    )
