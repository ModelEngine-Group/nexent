# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Cross-tenant discovery exposes only attested summary scheduling identities."""

import sqlalchemy as sa
from contracts.knowledge_summary import SUMMARY_DISPATCH_DATASET
from nexent.storage.models import StorageScope

from infrastructure.rdb.knowledge_deletion_metadata import knowledge
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)


def bind_summary_dispatch(engine):
    schedule = knowledge.c.summary_schedule
    projection = sa.select(knowledge.c.knowledge_id, knowledge.c.tenant_id, knowledge.c.index_name,
        schedule['user_id'].as_string().label('user_id'), knowledge.c.delete_flag).where(
        knowledge.c.summary_frequency.is_not(None), schedule.is_not(None), knowledge.c.knowledge_sources == 'elasticsearch',
        schedule['schema_version'].as_integer() == 1,
        schedule['user_id'].as_string().is_not(None),
    ).subquery(SUMMARY_DISPATCH_DATASET)
    definition = DatasetDefinition(SUMMARY_DISPATCH_DATASET, 'knowledge_id', tuple(FieldDefinition(c.name,
        'integer' if c.name == 'knowledge_id' else 'string', nullable=c.name != 'knowledge_id') for c in projection.c),
        frozenset({'management'}), tenant_field='tenant_id', active_field='delete_flag', allow_system=True)
    return SQLRecordStore(StorageScope('management', None, 'summary-dispatch', {SUMMARY_DISPATCH_DATASET}, system=True),
        DatasetCatalog((definition,)), {SUMMARY_DISPATCH_DATASET: projection}, engine, revision_fields={})
