# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only scheduling identities; the coordinator opens actor-scoped resources separately."""

from nexent.storage.models import StorageScope
from sqlalchemy import and_, case, or_, select

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
    ingestion_user = files.c.ingestion_request['user_id'].as_string()
    deletion_user = files.c.deletion_request['user_id'].as_string()
    deletion_scope = files.c.deletion_request['scope'].as_string()
    deleting = and_(
        files.c.deletion_request.is_not(None), deletion_user.is_not(None),
        or_(
            and_(deletion_scope == 'full', or_(
                and_(files.c.status == 'UPLOADING', files.c.stage.in_(('SOURCE_UPLOAD', 'SOURCE_CONFIRMED', 'SOURCE_ACCOUNTED', 'SOURCE_REVIEW'))),
                and_(files.c.status == 'UPLOADED', files.c.stage == 'UPLOAD'),
                and_(files.c.status == 'DELETE_REQUESTED', files.c.stage.in_(
                    ('DELETE_ACCEPTED', 'DELETE_RUNTIME_SUBMITTING', 'DELETE_RUNTIME_PENDING',
                     'DELETE_CLEANSE_PENDING', 'DELETE_SOURCE_PENDING', 'DELETE_SOURCE_DELETING'))),
            )),
            and_(deletion_scope == 'source_only', files.c.status == 'COMPLETED',
                 files.c.stage.in_(('DELETE_ACCEPTED', 'DELETE_SOURCE_DELETING'))),
        ),
    )
    projection = (
        select(
            *(files.c[name] for name in names),
            case((deleting, deletion_user), else_=ingestion_user).label('user_id'),
            case((deleting, 'delete'), else_='ingest').label('operation'),
        )
        .where(or_(deleting, and_(
            files.c.deletion_request.is_(None),
            files.c.ingestion_request.is_not(None),
            ingestion_user.is_not(None),
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
        )))
        .subquery(DATASET)
    )
    definition = DatasetDefinition(
        DATASET,
        "file_id",
        tuple(
            FieldDefinition(name, "string", nullable=True)
            for name in (*names, "user_id", 'operation')
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
