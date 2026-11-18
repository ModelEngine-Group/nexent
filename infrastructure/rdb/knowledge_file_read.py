# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only lifecycle and own/shared KB lookup bindings for Management readers."""

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_ingestion import FILE_KNOWLEDGE_READ_DATASET as KNOWLEDGE
from contracts.knowledge_ingestion import FILE_READ_DATASET as FILES
from nexent.storage.models import StorageScope
from sqlalchemy import literal, select

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.knowledge_search_records import KnowledgeRecord
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

knowledge, files = KnowledgeRecord.__table__, KnowledgeFileLifecycle.__table__


def bind_readable_knowledge(actor, engine):
    names = (
        "knowledge_id",
        "embedding_model_id",
        "deletion_request",
        "index_name",
        "created_by",
        "group_ids",
        "ingroup_permission",
        "knowledge_sources",
        "delete_flag",
    )
    projection = select(
        *(knowledge.c[name] for name in names),
        knowledge.c.tenant_id.label("resource_tenant_id"),
        literal(actor.tenant_id).label("tenant_id"),
    )
    projection = projection.where(
        knowledge.c.tenant_id.in_((actor.tenant_id, ASSET_OWNER_TENANT_ID))
    ).subquery(KNOWLEDGE)
    definition = DatasetDefinition(
        KNOWLEDGE,
        "knowledge_id",
        tuple(
            FieldDefinition(
                c.name,
                "object" if c.name == 'deletion_request' else "integer" if c.name in {"knowledge_id", "embedding_model_id"} else "string",
                nullable=True,
            )
            for c in projection.c
        ),
        frozenset({"management"}),
        tenant_field="tenant_id",
        active_field="delete_flag",
    )
    return SQLRecordStore(
        StorageScope("management", actor.tenant_id, actor.user_id, {KNOWLEDGE}),
        DatasetCatalog((definition,)),
        {KNOWLEDGE: projection},
        engine,
        revision_fields={},
    )


def file_read_catalog():
    names = (
        "file_id",
        "tenant_id",
        "knowledge_id",
        "index_name",
        "object_name",
        "local_source_path",
        "original_filename",
        "file_size",
        "status",
        "stage",
        "cleanse_status",
        "runtime_status",
        "processed_chunks",
        "total_chunks",
        "process_task_id",
        "forward_task_id",
        "error_code",
        "error_message",
        "error_stage",
        "failed_at",
        "uploaded_at",
        "create_time",
        "update_time",
        "delete_flag",
        "created_by",
        "updated_by",
        'deletion_request',
    )
    integers = {"knowledge_id", "file_size", "processed_chunks", "total_chunks"}
    definition = DatasetDefinition(
        FILES,
        "file_id",
        tuple(
            FieldDefinition(
                name,
                'object' if name == 'deletion_request' else "integer" if name in integers else "string",
                nullable=files.c[name].nullable,
            )
            for name in names
        ),
        frozenset({"management"}),
        tenant_field="tenant_id",
    )
    return definition, files


def bind_file_reads(tenant_id, user_id, engine):
    definition, table = file_read_catalog()
    return SQLRecordStore(
        StorageScope("management", tenant_id, user_id, {FILES}),
        DatasetCatalog((definition,)),
        {FILES: table},
        engine,
        revision_fields={},
        audit_mappings={
            FILES: RecordAudit(
                "create_time",
                "update_time",
                "created_by",
                "updated_by",
                extra_dates=frozenset({"failed_at", "uploaded_at"}),
            )
        },
    )
