# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit system read grant fixed to one Management upload-owner service."""

from nexent.storage.errors import InvalidInput
from nexent.storage.models import StorageScope
from sqlalchemy import select

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

DATASET = "source_reconciliation_candidates"


def bind_source_candidates(owner_service, engine):
    if not isinstance(owner_service, str) or not 0 < len(owner_service) <= 32:
        raise InvalidInput()
    table = KnowledgeFileLifecycle.__table__
    names = [
        "file_id",
        "tenant_id",
        "created_by",
        "updated_by",
        "create_time",
        "update_time",
        "delete_flag",
        "version",
        "bucket_name",
        "object_name",
        "upload_owner_service",
        "source_upload_started_at",
        "source_reconcile_after",
    ]
    projection = (
        select(*(table.c[name] for name in names))
        .where(
            table.c.upload_owner_service == owner_service,
            table.c.status == "UPLOADING",
            table.c.stage == "SOURCE_UPLOAD",
            table.c.source_upload_sha256.is_not(None),
            table.c.source_upload_started_at.is_not(None),
        )
        .subquery(DATASET)
    )
    fields = tuple(
        FieldDefinition(
            name,
            "integer" if name == "version" else "string",
            nullable=projection.c[name].nullable,
        )
        for name in names
    )
    definition = DatasetDefinition(
        DATASET,
        "file_id",
        fields,
        frozenset({"management"}),
        tenant_field="tenant_id",
        active_field="delete_flag",
        allow_system=True,
    )
    return SQLRecordStore(
        StorageScope(
            "management", None, "source-reconciliation", {DATASET}, system=True
        ),
        DatasetCatalog((definition,)),
        {DATASET: projection},
        engine,
        revision_fields={},
        audit_mappings={
            DATASET: RecordAudit(
                "create_time",
                "update_time",
                "created_by",
                "updated_by",
                extra_dates=frozenset(
                    {"source_upload_started_at", "source_reconcile_after"}
                ),
            )
        },
    )
