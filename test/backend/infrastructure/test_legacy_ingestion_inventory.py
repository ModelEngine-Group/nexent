# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from time import monotonic

import pytest
import sqlalchemy as sa
from contracts.knowledge_maintenance import LEGACY_INGESTION_INVENTORY
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import OperationContext, StorageScope

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.legacy_ingestion_inventory import (
    bind_legacy_ingestion_inventory,
)

DATASET = LEGACY_INGESTION_INVENTORY


def test_legacy_inventory_reads_only_an_aggregate_across_tenants():
    files = KnowledgeFileLifecycle.__table__
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {files.schema}")
            conn.exec_driver_sql(
                f"CREATE TABLE {files.fullname} (tenant_id TEXT, delete_flag TEXT, ingestion_request JSON, status TEXT)"
            )
            conn.exec_driver_sql(
                f"INSERT INTO {files.fullname} VALUES (?, ?, ?, ?)",
                [
                    ("tenant-a", "N", None, "PROCESSING"),
                    ("tenant-b", "N", None, "FORWARDING"),
                    ("tenant-b", "N", "{}", "PROCESSING"),
                    ("tenant-a", "Y", None, "FORWARDING"),
                    ("tenant-a", "N", None, "UPLOADED"),
                ],
            )

        context = OperationContext("inventory-test", monotonic() + 5)
        scope = StorageScope("management", None, "operator", {DATASET}, system=True)
        store = bind_legacy_ingestion_inventory(scope, engine)
        try:
            assert store.get(DATASET, "files", context=context) == {"id": "files", "count": 2}
            with pytest.raises(ScopeDenied):
                store.delete(DATASET, "files", context=context)
        finally:
            store.close()
        for role, tenant, system in [("runtime", None, True), ("management", "tenant-a", False)]:
            scope = StorageScope(role, tenant, "operator", {DATASET}, system=system)
            with pytest.raises(ScopeDenied):
                bind_legacy_ingestion_inventory(scope, engine)
    finally:
        engine.dispose()
