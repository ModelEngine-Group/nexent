# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant-scoped source and storage-ledger records in one local transaction domain."""

from contracts.knowledge import KEY_TENANT_HARD_LIMIT_BYTES
from sqlalchemy import select

from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.source_binding import DATASET as SOURCE
from infrastructure.rdb.source_binding import source_catalog
from infrastructure.rdb.storage_ledger import LEDGER, ledger_catalog
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

QUOTA = "upload_tenant_config"


def bind_upload_records(scope, engine, *, with_policy=False):
    source, source_table, source_audit = source_catalog()
    ledger, table, ledger_audit = ledger_catalog()
    definitions = [source, ledger]
    tables = {SOURCE: source_table, LEDGER: table}
    if with_policy:
        names = (
            "tenant_config_id",
            "tenant_id",
            "config_key",
            "config_value",
            "delete_flag",
        )
        config_table = TenantConfig.__table__
        config = (
            select(*(config_table.c[name] for name in names))
            .where(config_table.c.config_key == KEY_TENANT_HARD_LIMIT_BYTES)
            .subquery(QUOTA)
        )
        definitions.append(
            DatasetDefinition(
                QUOTA,
                "tenant_config_id",
                tuple(
                    FieldDefinition(
                        name,
                        "integer" if name == "tenant_config_id" else "string",
                        nullable=config.c[name].nullable,
                    )
                    for name in names
                ),
                frozenset({"management"}),
                tenant_field="tenant_id",
                active_field="delete_flag",
            )
        )
        tables[QUOTA] = config
    return SQLRecordStore(
        scope,
        DatasetCatalog(tuple(definitions)),
        tables,
        engine,
        revision_fields={SOURCE: "version", LEDGER: "version"},
        audit_mappings={
            SOURCE: source_audit,
            LEDGER: ledger_audit,
        },
    )
