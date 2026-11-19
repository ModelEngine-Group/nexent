# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind tenant configuration mutations to an explicitly authorized actor."""

from contextlib import contextmanager

from nexent.storage.models import StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.record_audit import RecordAudit
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)
from infrastructure.tenant_quota_read import bind_quota_identity, config_table

CONFIGS = 'quota_write_configs'


def bind_quota_write_records(actor, tenant, engine, *, writable=True):
    fields = ('tenant_config_id', 'tenant_id', 'user_id', 'value_type', 'config_key', 'config_value', 'delete_flag',
              'create_time', 'update_time', 'created_by', 'updated_by')
    definition = DatasetDefinition(CONFIGS, 'tenant_config_id', tuple(
        FieldDefinition(name, 'integer' if name == 'tenant_config_id' else 'string',
                        nullable=config_table.c[name].nullable) for name in fields
    ), frozenset({'management'}), frozenset({'management'}) if writable else frozenset(),
        tenant_field='tenant_id', active_field='delete_flag')
    return SQLRecordStore(StorageScope('management', tenant, actor.user_id, {CONFIGS}),
        DatasetCatalog((definition,)), {CONFIGS: config_table}, engine, revision_fields={CONFIGS: None},
        audit_mappings={CONFIGS: RecordAudit('create_time', 'update_time', 'created_by', 'updated_by')})


@contextmanager
def quota_write_ports(actor, *, context):
    # Pre-commit live identity checks need a connection alongside the write.
    engine, owned = record_engine(context, connections=2), []
    try:
        identity = bind_quota_identity(actor, engine)
        owned.append(identity)

        def records(tenant):
            port = bind_quota_write_records(actor, tenant, engine)
            owned.append(port)
            return port

        yield identity, records
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])
