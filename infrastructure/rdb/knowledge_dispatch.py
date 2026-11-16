# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only Runtime scheduling metadata, excluding all previously begun attempts."""

from nexent.storage.models import StorageScope
from sqlalchemy import select

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
        "job_id", "tenant_id", "user_id", "knowledge_id", "file_id", "file_version",
        "create_time", "update_time", "created_by", "updated_by", "delete_flag",
    )
    projection = select(*(jobs.c[name] for name in names)).where(
        jobs.c.operation == "upload",
        jobs.c.status == "queued",
        jobs.c.write_started.is_(False),
        jobs.c.reconcile_required.is_(False),
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
