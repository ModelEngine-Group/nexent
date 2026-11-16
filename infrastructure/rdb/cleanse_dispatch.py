# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""System discovery exposes KB scheduling metadata without job payload or writes."""

from contracts.knowledge_cleanse import CLEANSE_DISPATCH_DATASET as DATASET
from nexent.storage.models import StorageScope
from sqlalchemy import select

from infrastructure.rdb.cleanse_jobs import cleanse_jobs
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


def bind_cleanse_dispatch(engine):
    names = (
        "id",
        "job_id",
        "tenant_id",
        "user_id",
        "status",
        "lease_until",
        "create_time",
        "update_time",
        "created_by",
        "updated_by",
        "delete_flag",
    )
    projection = (
        select(*(cleanse_jobs.c[name] for name in names))
        .where(
            cleanse_jobs.c.scope_kind == "knowledge",
            cleanse_jobs.c.reconcile_required.is_(False),
            cleanse_jobs.c.status.in_(("queued", "running")),
        )
        .subquery(DATASET)
    )
    definition = DatasetDefinition(
        DATASET,
        "id",
        tuple(
            FieldDefinition(
                name,
                "integer" if name == "id" else "string",
                nullable=projection.c[name].nullable,
            )
            for name in names
        ),
        frozenset({"management"}),
        tenant_field="tenant_id",
        active_field="delete_flag",
        allow_system=True,
    )
    return SQLRecordStore(
        StorageScope("management", None, "cleanse-dispatch", {DATASET}, system=True),
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
                extra_dates=frozenset({"lease_until"}),
            )
        },
    )
