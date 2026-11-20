# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restricted lifecycle records for Management's persistent ingestion coordinator."""

import sqlalchemy as sa
from contracts.knowledge_ingestion import (
    INGESTION_DATASET,
    LEGACY_FILE_ID_OCCUPANCY,
    is_canonical_file_id,
)
from nexent.storage.errors import InvalidInput
from nexent.storage.models import StorageScope

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

files = KnowledgeFileLifecycle.__table__


def bind_legacy_file_id_occupancy(actor_id, file_id, engine):
    if not is_canonical_file_id(file_id):
        raise InvalidInput()
    projection = sa.select(
        sa.literal(file_id).label("file_id"),
        sa.func.count().label("count"),
    ).where(files.c.file_id == file_id).subquery(LEGACY_FILE_ID_OCCUPANCY)
    projection.primary_key.add(projection.c.file_id)
    definition = DatasetDefinition(
        LEGACY_FILE_ID_OCCUPANCY, "file_id",
        (FieldDefinition("file_id", "string"), FieldDefinition("count", "integer")),
        frozenset({"management"}), allow_system=True,
    )
    return SQLRecordStore(
        StorageScope("management", None, actor_id, {LEGACY_FILE_ID_OCCUPANCY}, system=True),
        DatasetCatalog((definition,)), {LEGACY_FILE_ID_OCCUPANCY: projection}, engine, revision_fields={},
    )


def ingestion_catalog():
    names = (
        "file_id",
        "tenant_id",
        "knowledge_id",
        "index_name",
        "original_filename",
        "file_size",
        "storage_object_id",
        "bucket_name",
        "object_name",
        "local_source_path",
        "status",
        "stage",
        "source_generation",
        "source_space",
        "source_key",
        "source_revision",
        "source_sha256",
        "ingestion_request",
        "deletion_request",
        "processing_attempt",
        "process_task_id",
        "forward_task_id",
        "parent_task_id",
        "cleanse_status",
        "runtime_status",
        "processed_chunks",
        "total_chunks",
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
    integers = {"knowledge_id", "source_generation", "processing_attempt", "version", "file_size", "storage_object_id", "processed_chunks", "total_chunks"}
    fields = tuple(
        FieldDefinition(
            name,
            "object"
            if name in {"ingestion_request", "deletion_request"}
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
