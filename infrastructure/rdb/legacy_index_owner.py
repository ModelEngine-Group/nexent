# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exact-index ownership counts include deleted history without exposing other tenants."""

import sqlalchemy as sa
from contracts.knowledge_maintenance import LEGACY_INDEX_OWNER
from nexent.storage.models import StorageScope

from infrastructure.rdb.knowledge_deletion_metadata import knowledge
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


def bind_legacy_index_owner(actor, knowledge_id, index_name, engine):
    selected = sa.and_(knowledge.c.knowledge_id == knowledge_id, knowledge.c.tenant_id == actor.tenant_id,
                       knowledge.c.delete_flag == 'N')
    projection = sa.select(sa.literal(index_name).label('index_name'), sa.func.count().label('owner_count'),
        sa.func.coalesce(sa.func.sum(sa.case((selected, 1), else_=0)), 0).label('selected_owner_count')).where(
        knowledge.c.index_name == index_name).subquery(LEGACY_INDEX_OWNER)
    # The exact-index aggregate has one stable logical key even when its count is zero.
    projection.primary_key.add(projection.c.index_name)
    definition = DatasetDefinition(LEGACY_INDEX_OWNER, 'index_name', (FieldDefinition('index_name', 'string'),
        FieldDefinition('owner_count', 'integer'), FieldDefinition('selected_owner_count', 'integer')),
        frozenset({'management'}), allow_system=True)
    return SQLRecordStore(StorageScope('management', None, actor.user_id, {LEGACY_INDEX_OWNER}, system=True),
        DatasetCatalog((definition,)), {LEGACY_INDEX_OWNER: projection}, engine, revision_fields={})
