# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind a finite privileged discovery view without granting a system handle."""

from contextlib import contextmanager

import sqlalchemy as sa
from nexent.storage.models import StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)
from infrastructure.tenant_quota_read import (
    bind_quota_identity,
    bind_tenant_quota_records,
    config_table,
)

DISCOVERY = 'platform_quota_tenants'


def bind_platform_quota_discovery(actor, engine):
    table = config_table
    grouped = sa.select(
        table.c.tenant_id, sa.func.min(table.c.tenant_config_id).label('first_id'),
        sa.func.max(table.c.create_time).label('latest_created_at'),
    ).where(
        table.c.delete_flag == 'N', table.c.tenant_id.is_not(None),
    ).group_by(table.c.tenant_id).subquery()
    projection = sa.select(
        table.c.tenant_config_id, grouped.c.tenant_id,
        sa.literal(actor.tenant_id).label('scope_tenant_id'),
        sa.cast(grouped.c.latest_created_at, sa.String()).label('latest_created_at'),
    ).select_from(grouped.join(table, table.c.tenant_config_id == grouped.c.first_id)).subquery(DISCOVERY)
    definition = DatasetDefinition(DISCOVERY, 'tenant_config_id', (
        FieldDefinition('tenant_config_id', 'integer'),
        FieldDefinition('tenant_id', 'string'), FieldDefinition('scope_tenant_id', 'string'),
        FieldDefinition('latest_created_at', 'string', nullable=True),
    ), frozenset({'management'}), tenant_field='scope_tenant_id')
    return SQLRecordStore(
        StorageScope('management', actor.tenant_id, actor.user_id, {DISCOVERY}),
        DatasetCatalog((definition,)), {DISCOVERY: projection}, engine, revision_fields={},
    )


@contextmanager
def platform_quota_read_ports(actor, *, context):
    engine, owned = record_engine(context), []
    try:
        identity = bind_quota_identity(actor, engine)
        owned.append(identity)

        def discovery():
            port = bind_platform_quota_discovery(actor, engine)
            owned.append(port)
            return port

        def records(tenant):
            port = bind_tenant_quota_records(actor, tenant, engine)
            owned.append(port)
            return port

        yield identity, discovery, records
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])
