# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Only the signed KB metadata grant permits this resource-tenant model projection."""

from contextlib import contextmanager

from nexent.storage.models import StorageScope
from sqlalchemy import select

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.model_record import ModelRecord
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)

DISPLAY = 'knowledge_model_display'


def bind_knowledge_model_display(actor, grant, engine):
    table = ModelRecord.__table__
    names = ('model_id', 'tenant_id', 'display_name', 'model_type', 'delete_flag')
    projection = select(*(table.c[name] for name in names)).subquery(DISPLAY)
    definition = DatasetDefinition(DISPLAY, 'model_id', tuple(FieldDefinition(name,
        'integer' if name == 'model_id' else 'string', nullable=table.c[name].nullable) for name in names),
        frozenset({'runtime'}), tenant_field='tenant_id', active_field='delete_flag')
    return SQLRecordStore(StorageScope('runtime', grant.resource_tenant_id, actor.user_id, {DISPLAY}),
        DatasetCatalog((definition,)), {DISPLAY: projection}, engine, revision_fields={})


@contextmanager
def knowledge_model_display_ports(actor, grant, *, context):
    engine, records = record_engine(context), None
    try:
        records = bind_knowledge_model_display(actor, grant, engine)
        yield records
    finally:
        close_owned(context, ([records.close] if records is not None else []) + [engine.dispose])
