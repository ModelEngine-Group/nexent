# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Aggregate ledger evidence for outstanding legacy ingestion work."""

import sqlalchemy as sa
from contracts.knowledge_maintenance import LEGACY_INGESTION_INVENTORY, LEGACY_TASK_REFERENCES
from nexent.storage.errors import ScopeDenied, Unavailable
from nexent.storage.models import Comparison, PageRequest, RecordQuery

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


def bind_legacy_ingestion_inventory(scope, engine):
    files = KnowledgeFileLifecycle.__table__
    projection = sa.select(sa.literal("files").label("id"), sa.func.count().label("count")).where(
        files.c.delete_flag == "N",
        files.c.ingestion_request.is_(None),
        files.c.status.in_(("PROCESSING", "FORWARDING")),
    ).subquery(LEGACY_INGESTION_INVENTORY)
    projection.primary_key.add(projection.c.id)
    definition = DatasetDefinition(
        LEGACY_INGESTION_INVENTORY, "id", (FieldDefinition("id", "string"), FieldDefinition("count", "integer")),
        frozenset({"management"}), allow_system=True,
    )
    return SQLRecordStore(
        scope, DatasetCatalog((definition,)), {LEGACY_INGESTION_INVENTORY: projection}, engine, revision_fields={},
    )


def bind_legacy_task_references(scope, engine):
    if not scope.system:
        raise ScopeDenied()
    files = KnowledgeFileLifecycle.__table__
    task_fields = ("process_task_id", "forward_task_id", "parent_task_id")
    live = [
        sa.select(files.c[name].label("task_id"), files.c.file_id).where(
            files.c.ingestion_request.is_(None), files.c[name].is_not(None),
        )
        for name in task_fields
    ]
    intent = files.c.ingestion_request
    snapshot = intent["legacy_snapshot"]
    archived = []
    for name in task_fields:
        task = snapshot["task_references"][name].as_string()
        archived.append(sa.select(task.label("task_id"), files.c.file_id).where(
            intent["file_id"].as_string() == files.c.file_id,
            sa.cast(intent["knowledge_id"].as_string(), sa.String) == sa.cast(files.c.knowledge_id, sa.String),
            snapshot["tenant_id"].as_string() == files.c.tenant_id,
            snapshot["mode"].as_string() == "rebuild_source",
            sa.cast(snapshot["legacy_quiesced"].as_string(), sa.String).in_(("true", "1")),
            sa.func.length(snapshot["task_archive_sha256"].as_string()) == 64,
            task.is_not(None),
        ))
    legacy_references = sa.union_all(*live, *archived).subquery()
    projection = sa.select(
        legacy_references.c.task_id,
        sa.func.count(sa.distinct(legacy_references.c.file_id)).label("count"),
    ).group_by(legacy_references.c.task_id).subquery(LEGACY_TASK_REFERENCES)
    projection.primary_key.add(projection.c.task_id)
    definition = DatasetDefinition(
        LEGACY_TASK_REFERENCES, "task_id",
        (FieldDefinition("task_id", "string"), FieldDefinition("count", "integer")),
        frozenset({"management"}), allow_system=True,
    )
    return SQLRecordStore(
        scope, DatasetCatalog((definition,)), {LEGACY_TASK_REFERENCES: projection}, engine,
        revision_fields={},
    )


def legacy_task_reference_counts(records, task_ids, *, context):
    page = records.query(
        LEGACY_TASK_REFERENCES, RecordQuery(where=Comparison("task_id", "in", task_ids)),
        PageRequest(limit=len(task_ids)), context=context,
    )
    if page.next_cursor is not None:
        raise Unavailable(operation_id=context.operation_id)
    return {row["task_id"]: row["count"] for row in page.items}
