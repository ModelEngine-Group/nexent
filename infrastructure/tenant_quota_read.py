# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read only the explicitly authorized tenant's allocation metadata."""

from contextlib import contextmanager
from dataclasses import replace

from nexent.storage.models import StorageScope

from infrastructure.knowledge_catalog import knowledge as knowledge_table
from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.rdb.storage_ledger import LEDGER, ledger_catalog
from infrastructure.rdb.tenant_config_record import TenantConfig
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

CATALOG, CONFIGS = "quota_read_knowledge", "quota_read_configs"
config_table = TenantConfig.__table__


def bind_tenant_quota_records(actor, tenant_id, engine, *, usage=False):
    schemas = []
    knowledge_fields = ("knowledge_id", "tenant_id", "quota_limit_bytes", "delete_flag")
    if usage:
        knowledge_fields += (
            "index_name", "knowledge_name", "knowledge_sources", "embedding_model_id",
            "created_by", "group_ids", "ingroup_permission",
        )
    for name, table, key, names, active in (
        (
            CATALOG,
            knowledge_table,
            "knowledge_id",
            knowledge_fields,
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
                        in {"knowledge_id", "quota_limit_bytes", "tenant_config_id", "embedding_model_id"}
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
    tables = {CATALOG: knowledge_table, CONFIGS: config_table}
    audits = {}
    if usage:
        definition, table, audit = ledger_catalog()
        schemas.append(replace(definition, write_roles=frozenset()))
        tables[LEDGER] = table
        audits[LEDGER] = audit
    return SQLRecordStore(
        StorageScope("management", tenant_id, actor.user_id, set(tables)),
        DatasetCatalog(tuple(schemas)),
        tables,
        engine,
        revision_fields={},
        audit_mappings=audits,
    )


@contextmanager
def tenant_quota_read_ports(actor, *, context, usage=False):
    engine, owned = record_engine(context), []
    try:
        identity = bind_quota_identity(actor, engine)
        owned.append(identity)

        def records(tenant_id):
            port = bind_tenant_quota_records(actor, tenant_id, engine, usage=usage)
            owned.append(port)
            return port

        yield identity, records
    finally:
        close_owned(
            context, [port.close for port in reversed(owned)] + [engine.dispose]
        )


def bind_quota_identity(actor, engine):
    return bind_cleanse_resources(
        StorageScope('management', actor.tenant_id, actor.user_id,
                     {'cleanse_memberships', 'cleanse_accounts'}),
        engine,
    )
