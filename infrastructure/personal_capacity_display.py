# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only identity display projections for explicitly selected KB creators."""

from contextlib import contextmanager

import sqlalchemy as sa
from nexent.storage.models import StorageScope

from infrastructure.rdb.account_record import UserAccount, UserTenant
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

EMAILS, CAS = 'personal_capacity_emails', 'personal_capacity_cas'
accounts_table, members_table = UserAccount.__table__, UserTenant.__table__
# This is a read projection of the existing identity table, not a schema migration.
oauth_table = sa.Table('user_oauth_account_t', sa.MetaData(),
    sa.Column('oauth_account_id', sa.Integer, primary_key=True),
    sa.Column('user_id', sa.String(100)), sa.Column('provider', sa.String(30)),
    sa.Column('provider_username', sa.String(200)), sa.Column('delete_flag', sa.String(1)), schema='nexent')


def bind_personal_capacity_display(actor, tenant, engine):
    def active_member(user_id):
        return sa.select(members_table.c.user_tenant_id).where(
            members_table.c.user_id == user_id, members_table.c.delete_flag == 'N').exists()

    emails = sa.select(accounts_table.c.account_id, accounts_table.c.user_id, accounts_table.c.user_email,
        sa.literal(tenant).label('tenant_id')).where(accounts_table.c.delete_flag == 'N',
            active_member(accounts_table.c.user_id)).subquery(EMAILS)
    cas = sa.select(oauth_table.c.oauth_account_id, oauth_table.c.user_id, oauth_table.c.provider_username,
        sa.literal(tenant).label('tenant_id')).where(oauth_table.c.provider == 'cas', oauth_table.c.delete_flag == 'N',
            active_member(oauth_table.c.user_id)).subquery(CAS)
    tables = {EMAILS: emails, CAS: cas}
    definitions = tuple(DatasetDefinition(name, key,
        tuple(FieldDefinition(column.name, 'integer' if column.name == key else 'string', nullable=column.name != key)
            for column in projection.c), frozenset({'management'}), tenant_field='tenant_id')
        for name, projection, key in [(EMAILS, emails, 'account_id'), (CAS, cas, 'oauth_account_id')])
    return SQLRecordStore(StorageScope('management', tenant, actor.user_id, set(tables)),
        DatasetCatalog(definitions), tables, engine, revision_fields={})


@contextmanager
def personal_capacity_display_ports(actor, tenant, *, context):
    engine, owned = record_engine(context), []
    try:
        records = bind_personal_capacity_display(actor, tenant, engine)
        owned.append(records)
        yield records
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])
