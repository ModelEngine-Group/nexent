# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime-only composition issues exclusive collection power after signed authorization."""

from contextlib import contextmanager
from dataclasses import replace

from contracts.knowledge_base_deletion import (
    BASE_DELETION_DATASET,
    RUNTIME_FILES,
    RUNTIME_JOBS,
)
from nexent.storage.models import StorageScope

from infrastructure.knowledge_vectors import _configured_client, vector_binding
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_base_deletions import bind_base_deletion_records
from infrastructure.vdb.vector_store import ElasticsearchVectorStore


@contextmanager
def knowledge_base_deletion_ports(actor, grant, *, context):
    engine, owned = record_engine(context), []
    try:
        records = bind_base_deletion_records(StorageScope('runtime', actor.tenant_id, actor.user_id,
                                                          {BASE_DELETION_DATASET, RUNTIME_FILES, RUNTIME_JOBS}), engine)
        owned.append(records)
        binding = replace(vector_binding(actor.tenant_id, grant.collection, None), owns_collection=True)
        vectors = ElasticsearchVectorStore(StorageScope('runtime', actor.tenant_id, actor.user_id, {grant.collection}),
                                            (binding,), _configured_client)
        owned.append(vectors)
        vectors.capabilities.require('vector.collection.exists', 'vector.collection.delete-empty')
        yield records, vectors
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])
