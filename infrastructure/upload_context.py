# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind narrow upload metadata in the actual uploader's own namespace."""

from contextlib import contextmanager

from nexent.storage.models import StorageScope

from infrastructure.knowledge_catalog import knowledge
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.record_store import SQLRecordStore
from infrastructure.storage.catalog import (
    DatasetCatalog,
    DatasetDefinition,
    FieldDefinition,
)
from infrastructure.tenant_quota_read import bind_quota_identity

DATASET = 'upload_context_knowledge'


def bind_upload_context(actor, engine):
    fields = ('knowledge_id', 'tenant_id', 'index_name', 'ingroup_permission', 'delete_flag')
    definition = DatasetDefinition(DATASET, 'knowledge_id', tuple(
        FieldDefinition(name, 'integer' if name == 'knowledge_id' else 'string', nullable=knowledge.c[name].nullable)
        for name in fields
    ), frozenset({'management'}), tenant_field='tenant_id')
    return SQLRecordStore(StorageScope('management', actor.tenant_id, actor.user_id, {DATASET}),
                          DatasetCatalog((definition,)), {DATASET: knowledge}, engine, revision_fields={})


@contextmanager
def upload_context_ports(actor, *, context):
    engine, owned = record_engine(context), []
    try:
        identity = bind_quota_identity(actor, engine)
        owned.append(identity)

        def metadata():
            records = bind_upload_context(actor, engine)
            owned.append(records)
            return records

        yield identity, metadata
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])
