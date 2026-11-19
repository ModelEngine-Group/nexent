# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read only the explicitly authorized tenant's allocation metadata."""

from contextlib import contextmanager

from nexent.storage.models import StorageScope

from infrastructure.knowledge_catalog import knowledge as knowledge_table
from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

CATALOG, CONFIGS = "quota_read_knowledge", "quota_read_configs"
config_table = TenantConfig.__table__


def bind_tenant_quota_records(actor, tenant_id, engine):
    schemas = []
    for name, table, key, names, active in (
        (
            CATALOG,
            knowledge_table,
            "knowledge_id",
            ("knowledge_id", "tenant_id", "quota_limit_bytes", "delete_flag"),
            None,
        ),
        (
            CONFIGS,
            config_table,
            "tenant_config_id",
            (
                "tenant_config_id",
                "tenant_id",
                "config_key",
                "config_value",
                "delete_flag",
            ),
            "delete_flag",
        ),
    ):
        schemas.append(
            DatasetDefinition(
                name,
                key,
                tuple(
                    FieldDefinition(
                        field,
                        "integer"
                        if field
                        in {"knowledge_id", "quota_limit_bytes", "tenant_config_id"}
                        else "string",
                        nullable=True,
                    )
                    for field in names
                ),
                frozenset({"management"}),
                tenant_field="tenant_id",
                active_field=active,
            )
        )
    return SQLRecordStore(
        StorageScope("management", tenant_id, actor.user_id, {CATALOG, CONFIGS}),
        DatasetCatalog(tuple(schemas)),
        {CATALOG: knowledge_table, CONFIGS: config_table},
        engine,
        revision_fields={},
    )


@contextmanager
def tenant_quota_read_ports(actor, *, context):
    engine, owned = record_engine(context), []
    try:
        identity = bind_cleanse_resources(
            StorageScope(
                "management",
                actor.tenant_id,
                actor.user_id,
                {
                    "cleanse_memberships",
                    "cleanse_accounts",
                },
            ),
            engine,
        )
        owned.append(identity)

        def records(tenant_id):
            port = bind_tenant_quota_records(actor, tenant_id, engine)
            owned.append(port)
            return port

        yield identity, records
    finally:
        close_owned(
            context, [port.close for port in reversed(owned)] + [engine.dispose]
        )
