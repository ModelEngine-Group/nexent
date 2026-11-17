# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only scheduling identities; the coordinator opens actor-scoped resources separately."""

from nexent.storage.models import StorageScope
from sqlalchemy import and_, or_, select

from infrastructure.rdb import knowledge_ingestion
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

DATASET = "management_knowledge_ingestion_dispatch"


def bind_ingestion_dispatch(engine):
    files = knowledge_ingestion.files
    names = (
        "file_id",
        "tenant_id",
        "create_time",
        "update_time",
        "created_by",
        "updated_by",
        "delete_flag",
    )
    projection = (
        select(
            *(files.c[name] for name in names),
            files.c.ingestion_request["user_id"].as_string().label("user_id"),
        )
        .where(
            files.c.ingestion_request.is_not(None),
            files.c.ingestion_request["user_id"].as_string().is_not(None),
            or_(
                and_(files.c.status == "UPLOADED", files.c.stage == "INGEST_ACCEPTED"),
                and_(
                    files.c.status == "PROCESSING",
                    files.c.stage.in_(("CLEANSE_SUBMITTING", "CLEANSE_PENDING")),
                ),
                and_(
                    files.c.status == "FORWARDING",
                    files.c.stage.in_(("RUNTIME_SUBMITTING", "RUNTIME_PENDING")),
                ),
            ),
        )
        .subquery(DATASET)
    )
    definition = DatasetDefinition(
        DATASET,
        "file_id",
        tuple(
            FieldDefinition(name, "string", nullable=True)
            for name in (*names, "user_id")
        ),
        frozenset({"management"}),
        tenant_field="tenant_id",
        active_field="delete_flag",
        allow_system=True,
    )
    return SQLRecordStore(
        StorageScope(
            "management", None, "knowledge-ingestion-dispatch", {DATASET}, system=True
        ),
        DatasetCatalog((definition,)),
        {DATASET: projection},
        engine,
        revision_fields={},
        audit_mappings={
            DATASET: RecordAudit(
                "create_time", "update_time", "created_by", "updated_by"
            )
        },
    )
