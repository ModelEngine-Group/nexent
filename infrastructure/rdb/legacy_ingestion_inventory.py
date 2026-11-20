# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Aggregate ledger evidence for outstanding legacy ingestion work."""

import sqlalchemy as sa
from contracts.knowledge_maintenance import LEGACY_INGESTION_INVENTORY

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
