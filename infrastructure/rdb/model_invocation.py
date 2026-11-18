# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private Runtime execution records use read-only tenant-scoped StorageInterface handles."""

from datetime import datetime

import sqlalchemy as sa
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.model_record import ModelRecord
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

DATASET = 'runtime_model_invocation'
models = ModelRecord.__table__


def _kind(column):
    if isinstance(column.type, sa.Boolean): return 'boolean'
    if isinstance(column.type, sa.Integer): return 'integer'
    if isinstance(column.type, (sa.Float, sa.Numeric)): return 'number'
    if isinstance(column.type, sa.JSON):
        return 'array' if column.name in {'reasoning_controls','input_modalities','output_modalities'} else 'object'
    return 'string'


def bind_invocation_models(scope, engine):
    if (scope.system or scope.service_role != 'runtime' or scope.namespaces != {DATASET} or scope.resource_prefix):
        raise ScopeDenied()
    projection = sa.select(*(sa.cast(column, sa.String).label(column.name) if isinstance(column.type, sa.DateTime)
        else column for column in models.c)).subquery(DATASET)
    definition = DatasetDefinition(DATASET, 'model_id', tuple(FieldDefinition(column.name,_kind(column),nullable=column.nullable)
        for column in models.c), frozenset({'runtime'}), tenant_field='tenant_id',active_field='delete_flag')
    return SQLRecordStore(scope,DatasetCatalog((definition,)),{DATASET:projection},engine,revision_fields={})


def read_invocation_model(model_id, actor, *, context):
    engine, records = record_engine(context), None
    try:
        records = bind_invocation_models(StorageScope('runtime',actor.tenant_id,actor.user_id,{DATASET}),engine)
        row = records.get(DATASET,model_id,context=context)
        if row is not None:
            for name in ('create_time','update_time'):
                if row.get(name) is not None: row[name] = datetime.fromisoformat(row[name]).isoformat()
        return row
    finally:
        close_owned(context,([records.close] if records else [])+[engine.dispose])
