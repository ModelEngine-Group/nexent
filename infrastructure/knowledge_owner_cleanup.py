# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read only the actual issuer and requested owner's live identities through SI."""

from contextlib import contextmanager

import sqlalchemy as sa
from contracts.knowledge_admission import OWNER_CLEANUP_IDENTITIES as DATASET
from nexent.storage.models import StorageScope

from infrastructure.rdb.account_record import UserAccount, UserTenant
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

accounts, memberships = UserAccount.__table__, UserTenant.__table__


def bind_owner_cleanup_identities(actor, owner_user_id, engine):
    # The synthetic scope field bounds this two-identity projection; tenant_id remains authoritative.
    projection = sa.select(
        memberships.c.user_tenant_id, memberships.c.user_id, memberships.c.tenant_id,
        accounts.c.user_roles, memberships.c.delete_flag, sa.literal(actor.tenant_id).label('scope_tenant_id'),
    ).select_from(memberships.join(accounts, accounts.c.user_id == memberships.c.user_id)).where(
        memberships.c.delete_flag == 'N', accounts.c.delete_flag == 'N', sa.or_(
            memberships.c.user_id == actor.user_id,
            sa.and_(memberships.c.user_id == owner_user_id, memberships.c.tenant_id == actor.tenant_id),
        ),
    ).subquery(DATASET)
    definition = DatasetDefinition(DATASET, 'user_tenant_id', (
        FieldDefinition('user_tenant_id', 'integer'), FieldDefinition('user_id', 'string'),
        FieldDefinition('tenant_id', 'string'), FieldDefinition('user_roles', 'array'),
        FieldDefinition('delete_flag', 'string'), FieldDefinition('scope_tenant_id', 'string'),
    ), frozenset({'management'}), tenant_field='scope_tenant_id', active_field='delete_flag')
    return SQLRecordStore(StorageScope('management', actor.tenant_id, actor.user_id, {DATASET}),
                           DatasetCatalog((definition,)), {DATASET: projection}, engine, revision_fields={})


@contextmanager
def owner_cleanup_identity_ports(actor, owner_user_id, *, context):
    engine, owned = record_engine(context), []
    try:
        records = bind_owner_cleanup_identities(actor, owner_user_id, engine)
        owned.append(records)
        yield records
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])
