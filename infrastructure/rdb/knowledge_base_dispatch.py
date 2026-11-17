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
    projection = sa.select(
        knowledge.c.knowledge_id, knowledge.c.tenant_id, knowledge.c.index_name, knowledge.c.delete_flag,
        issuer.label('user_id'), owner.label('owner_user_id'), purpose.label('purpose'),
    ).where(
        knowledge.c.ingroup_permission == 'PRIVATE', knowledge.c.knowledge_sources == 'elasticsearch',
        knowledge.c.created_by == owner, issuer.is_not(None),
        purpose.in_(('user_deletion', 'tenant_deletion')),
        intent['phase'].as_string().in_(('files', 'collection_submitting', 'metadata_pending')),
        sa.exists(sa.select(1).where(member_scope, memberships.c.delete_flag == 'Y')),
        ~sa.exists(sa.select(1).where(member_scope, memberships.c.delete_flag == 'N')),
        sa.exists(sa.select(1).where(account_scope, accounts.c.delete_flag == 'Y')),
        ~sa.exists(sa.select(1).where(account_scope, accounts.c.delete_flag == 'N')),
    ).subquery(DATASET)
    definition = DatasetDefinition(DATASET, 'knowledge_id', tuple(
        FieldDefinition(column.name, 'integer' if column.name == 'knowledge_id' else 'string')
        for column in projection.c), frozenset({'management'}), tenant_field='tenant_id',
        active_field='delete_flag', allow_system=True)
    return SQLRecordStore(StorageScope('management', None, 'knowledge-base-dispatch', {DATASET}, system=True),
                           DatasetCatalog((definition,)), {DATASET: projection}, engine, revision_fields={})
