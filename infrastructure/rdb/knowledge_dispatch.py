# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only Runtime scheduling metadata, excluding all previously begun attempts."""

from nexent.storage.models import StorageScope
from sqlalchemy import and_, exists, or_, select

from infrastructure.rdb.knowledge_jobs import jobs
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

DATASET = "runtime_knowledge_dispatch"


def bind_knowledge_dispatch(engine):
    names = (
        "job_id", "tenant_id", "user_id", "knowledge_id", "file_id", "file_version", "operation",
        "create_time", "update_time", "created_by", "updated_by", "delete_flag",
    )
    writer = jobs.alias("covered_writer")
    active_writer = exists(select(writer.c.job_id).where(
        writer.c.tenant_id == jobs.c.tenant_id,
        writer.c.knowledge_id == jobs.c.knowledge_id,
        writer.c.file_id == jobs.c.file_id,
        writer.c.file_version <= jobs.c.file_version,
        writer.c.operation == "upload", writer.c.delete_flag == "N",
        writer.c.write_started.is_(True), writer.c.writer_ended.is_(False),
    ))
    projection = select(*(jobs.c[name] for name in names)).where(
        or_(and_(jobs.c.operation == "upload", jobs.c.status == "queued"),
            and_(jobs.c.operation == "delete", jobs.c.status == "cleanup_pending", ~active_writer)),
        jobs.c.write_started.is_(False),
        jobs.c.reconcile_required.is_(False),
        jobs.c.owner_id.is_(None),
    ).subquery(DATASET)
    definition = DatasetDefinition(
        DATASET, "job_id",
        tuple(FieldDefinition(
            name, "integer" if name in {"knowledge_id", "file_version"} else "string",
            nullable=projection.c[name].nullable,
        ) for name in names),
        frozenset({"runtime"}),
        tenant_field="tenant_id", active_field="delete_flag", allow_system=True,
    )
    return SQLRecordStore(
        StorageScope("runtime", None, "knowledge-dispatch", {DATASET}, system=True),
        DatasetCatalog((definition,)), {DATASET: projection}, engine,
        revision_fields={},
        audit_mappings={DATASET: RecordAudit("create_time", "update_time", "created_by", "updated_by")},
    )
