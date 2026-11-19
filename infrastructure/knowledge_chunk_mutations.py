# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Close every record handle and engine owned by a Runtime mutation operation."""

from contextlib import contextmanager

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_chunk_mutation import CHANGES, STATES
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.knowledge_vectors import (
    bind_knowledge_chunk_vectors,
    bind_knowledge_creation_vectors,
)
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_lifecycle import bind_knowledge_lifecycle


@contextmanager
def knowledge_chunk_mutation_ports(actor, *, context, resource_tenant_id=None):
    tenant = actor.tenant_id if resource_tenant_id is None else resource_tenant_id
    if tenant not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}:
        raise ScopeDenied()
    engine, records = record_engine(context), None
    try:
        scope = StorageScope("runtime", tenant, actor.user_id, {CHANGES, STATES})
        records = bind_knowledge_lifecycle(scope, engine, mode="mutation")
        yield records
    finally:
        close_owned(
            context, ([records.close] if records is not None else []) + [engine.dispose]
        )


@contextmanager
def knowledge_creation_vector_ports(actor, collection, dimensions, *, context, resource_tenant_id=None):
    context.remaining()
    vectors = bind_knowledge_creation_vectors(actor, collection, dimensions, resource_tenant_id=resource_tenant_id)
    try:
        yield vectors
    finally:
        close_owned(context, [vectors.close])


@contextmanager
def knowledge_chunk_vector_ports(actor, collection, *, context, resource_tenant_id=None, dimensions=None):
    context.remaining()
    vectors = bind_knowledge_chunk_vectors(actor, collection, resource_tenant_id=resource_tenant_id, dimensions=dimensions)
    try:
        yield vectors
    finally:
        close_owned(context, [vectors.close])
