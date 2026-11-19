# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Finite identity, metadata and permission handles for collection descriptions."""

from contextlib import contextmanager
from dataclasses import replace

import sqlalchemy as sa
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_search_records import KnowledgeRecord
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

METADATA = 'knowledge_collection_metadata'
PERMISSIONS = 'knowledge_collection_permissions'
# Existing global permission configuration has no tenant or audit columns.
permissions_table = sa.Table('role_permission_t', sa.MetaData(),
    sa.Column('role_permission_id', sa.Integer, primary_key=True),
    *(sa.Column(name, sa.String(30)) for name in ('user_role', 'permission_category', 'permission_type', 'permission_subtype')),
    schema='nexent')


def _port(actor, engine, name, projection, key):
    integers = {'knowledge_id', 'embedding_model_id', 'role_permission_id'}
    definition = DatasetDefinition(name, key, tuple(FieldDefinition(c.name,
        'integer' if c.name in integers else 'string', nullable=c.name not in {key, 'tenant_id', 'resource_tenant_id'}) for c in projection.c),
        frozenset({'management'}), tenant_field='tenant_id',
        active_field='delete_flag' if 'delete_flag' in projection.c else None)
    return SQLRecordStore(StorageScope('management', actor.tenant_id, actor.user_id, {name}),
        DatasetCatalog((definition,)), {name: projection}, engine, revision_fields={})


def bind_collection_metadata(actor, engine, *, cross_tenant=False):
    table = KnowledgeRecord.__table__
    names = ('knowledge_id', 'index_name', 'embedding_model_id', 'created_by', 'group_ids',
             'ingroup_permission', 'knowledge_sources', 'delete_flag')
    query = sa.select(*(table.c[name] for name in names), table.c.tenant_id.label('resource_tenant_id'),
                      sa.literal(actor.tenant_id).label('tenant_id'))
    if not cross_tenant:
        query = query.where(table.c.tenant_id.in_((actor.tenant_id, ASSET_OWNER_TENANT_ID)))
    return _port(actor, engine, METADATA, query.subquery(METADATA), 'knowledge_id')


def bind_collection_permissions(actor, engine):
    table = permissions_table
    query = sa.select(table.c.role_permission_id, sa.cast(sa.func.upper(table.c.user_role), sa.String(30)).label('user_role'),
        table.c.permission_category, sa.cast(sa.func.lower(table.c.permission_type), sa.String(30)).label('permission_type'),
        sa.cast(sa.func.lower(table.c.permission_subtype), sa.String(30)).label('permission_subtype'),
        sa.literal(actor.tenant_id).label('tenant_id')).subquery(PERMISSIONS)
    return _port(actor, engine, PERMISSIONS, query, 'role_permission_id')


@contextmanager
def collection_metadata_ports(actor, *, context):
    engine, owned = record_engine(context), []
    try:
        identity = bind_cleanse_resources(StorageScope('management', actor.tenant_id, actor.user_id,
            {'cleanse_memberships', 'cleanse_accounts', 'cleanse_group_memberships', 'cleanse_groups'}), engine)
        owned.append(identity)
        permissions = bind_collection_permissions(actor, engine)
        owned.append(permissions)

        def resources(*, cross_tenant):
            records = bind_collection_metadata(actor, engine, cross_tenant=cross_tenant)
            owned.append(records)
            return records

        yield identity, permissions, resources
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])


@contextmanager
def collection_metadata_vector_ports(actor, grant, *, context):
    """Only the metadata callback attests this possibly cross-tenant namespace."""
    from infrastructure.knowledge_vectors import _configured_client, vector_binding
    from infrastructure.vdb.vector_store import ElasticsearchVectorStore

    context.remaining()
    binding = replace(vector_binding(grant.resource_tenant_id, grant.collection, None,
        writable=False, allow_unembedded=True), owns_collection=True)
    port = ElasticsearchVectorStore(StorageScope('runtime', grant.resource_tenant_id, actor.user_id, {grant.collection}),
                                    (binding,), _configured_client)
    try:
        yield port
    finally:
        close_owned(context, [port.close])
