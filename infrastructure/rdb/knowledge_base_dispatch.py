# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read only admitted deprovision scheduling identities after target revocation."""

import sqlalchemy as sa
from nexent.storage.models import StorageScope

from infrastructure.rdb.account_record import UserAccount, UserTenant
from infrastructure.rdb.knowledge_deletion_metadata import knowledge
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

DATASET = 'management_knowledge_base_dispatch'
accounts, memberships = UserAccount.__table__, UserTenant.__table__


def bind_base_dispatch(engine):
    intent = knowledge.c.deletion_request
    owner = intent['owner_cleanup']['owner_user_id'].as_string()
    purpose = intent['owner_cleanup']['purpose'].as_string()
    issuer = intent['user_id'].as_string()
    member_scope = sa.and_(memberships.c.user_id == owner, memberships.c.tenant_id == knowledge.c.tenant_id)
    account_scope = accounts.c.user_id == owner
    owned = sa.and_(
        knowledge.c.ingroup_permission == 'PRIVATE', knowledge.c.created_by == owner,
        purpose.in_(('user_deletion', 'tenant_deletion')),
        intent['tenant_cleanup']['actor_tenant_id'].as_string().is_(None),
        sa.exists(sa.select(1).where(member_scope, memberships.c.delete_flag == 'Y')),
        ~sa.exists(sa.select(1).where(member_scope, memberships.c.delete_flag == 'N')),
        sa.exists(sa.select(1).where(account_scope, accounts.c.delete_flag == 'Y')),
        ~sa.exists(sa.select(1).where(account_scope, accounts.c.delete_flag == 'N')),
    )
    tenant = sa.and_(
        knowledge.c.ingroup_permission.in_(('EDIT', 'READ_ONLY')),
        owner.is_(None), intent['tenant_cleanup']['actor_tenant_id'].as_string().is_not(None),
        ~sa.exists(sa.select(1).where(memberships.c.tenant_id == knowledge.c.tenant_id, memberships.c.delete_flag == 'N')),
    )
    projection = sa.select(
        knowledge.c.knowledge_id, knowledge.c.tenant_id, knowledge.c.index_name, knowledge.c.delete_flag,
        issuer.label('user_id'), owner.label('owner_user_id'),
        sa.case((tenant, 'tenant_deletion'), else_=purpose).label('purpose'),
        sa.case((tenant, 'tenant'), else_='owner').label('cleanup_kind'),
    ).where(
        knowledge.c.knowledge_sources == 'elasticsearch', issuer.is_not(None),
        sa.or_(owned, tenant),
        intent['phase'].as_string().in_(('files', 'collection_submitting', 'metadata_pending')),
    ).subquery(DATASET)
    definition = DatasetDefinition(DATASET, 'knowledge_id', tuple(
        FieldDefinition(column.name, 'integer' if column.name == 'knowledge_id' else 'string',
                        nullable=column.name == 'owner_user_id')
        for column in projection.c), frozenset({'management'}), tenant_field='tenant_id',
        active_field='delete_flag', allow_system=True)
    return SQLRecordStore(StorageScope('management', None, 'knowledge-base-dispatch', {DATASET}, system=True),
                           DatasetCatalog((definition,)), {DATASET: projection}, engine, revision_fields={})
