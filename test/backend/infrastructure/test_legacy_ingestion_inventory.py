# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from time import monotonic

import pytest
import sqlalchemy as sa
from contracts.knowledge_maintenance import LEGACY_INGESTION_INVENTORY, LEGACY_TASK_REFERENCES
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import OperationContext, StorageScope

from infrastructure.rdb.knowledge_file_record import KnowledgeFileLifecycle
from infrastructure.rdb.legacy_ingestion_inventory import (
    bind_legacy_ingestion_inventory,
    bind_legacy_task_references,
    legacy_task_reference_counts,
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


def test_reference_evidence_counts_distinct_files_and_excludes_managed_ids():
    files = KnowledgeFileLifecycle.__table__
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {files.schema}")
            conn.exec_driver_sql(f"CREATE TABLE {files.fullname} (file_id TEXT PRIMARY KEY, tenant_id TEXT, "
                "delete_flag TEXT, ingestion_request JSON, process_task_id TEXT, forward_task_id TEXT, parent_task_id TEXT)")
            conn.exec_driver_sql(f"INSERT INTO {files.fullname} VALUES (?, ?, ?, ?, ?, ?, ?)", [
                ("a", "tenant-a", "N", None, "unique", "shared", "unique"),
                ("b", "tenant-b", "Y", None, "shared", None, None),
                ("c", "tenant-a", "N", "{}", "managed", None, "unique"),
            ])
        ctx = OperationContext("references-test", monotonic() + 5)
        scope = StorageScope("management", None, "operator", {LEGACY_TASK_REFERENCES}, system=True)
        with pytest.raises(ScopeDenied):
            bind_legacy_task_references(StorageScope("management", "tenant-a", "operator",
                {LEGACY_TASK_REFERENCES}), engine)
        store = bind_legacy_task_references(scope, engine)
        try:
            assert legacy_task_reference_counts(store, ["unique", "shared", "managed", "missing"], context=ctx) == {
                "unique": 1, "shared": 2,
            }
            with pytest.raises(ScopeDenied):
                store.delete(LEGACY_TASK_REFERENCES, "unique", context=ctx)
        finally:
            store.close()
    finally:
        engine.dispose()
