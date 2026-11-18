# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned Runtime-only record ports; Management metadata is obtained over AgentOS."""

from contextlib import contextmanager

from contracts.agentos_knowledge import KnowledgeChunksGrant
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.knowledge_objects import bind_knowledge_objects
from infrastructure.knowledge_vectors import bind_knowledge_vectors
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_dispatch import bind_knowledge_dispatch
from infrastructure.rdb.knowledge_jobs import (
    FILES,
    JOBS,
    bind_knowledge_jobs,
    bind_knowledge_manifest,
)


@contextmanager
def knowledge_dispatch_ports(*, context):
    engine, records = record_engine(context), None
    try:
        records = bind_knowledge_dispatch(engine)
        yield records
    finally:
        close_owned(
            context, ([records.close] if records is not None else []) + [engine.dispose]
        )


@contextmanager
def knowledge_runtime_ports(actor, *, context):
    engine, records = record_engine(context), None
    try:
        scope = StorageScope("runtime", actor.tenant_id, actor.user_id, {FILES, JOBS})
        records = bind_knowledge_jobs(scope, engine)
        yield records
    finally:
        close_owned(
            context, ([records.close] if records is not None else []) + [engine.dispose]
        )


@contextmanager
def knowledge_manifest_ports(actor, knowledge_id, *, context):
    engine, records = record_engine(context), None
    try:
        records = bind_knowledge_manifest(StorageScope('runtime', actor.tenant_id, actor.user_id, {FILES}), knowledge_id, engine)
        yield records
    finally:
        close_owned(context, ([records.close] if records is not None else []) + [engine.dispose])


@contextmanager
def knowledge_execution_ports(actor, grant, dimensions, *, context):
    objects = vectors = None
    try:
        objects = bind_knowledge_objects(actor, grant, context=context)
        vectors = bind_knowledge_vectors(actor, grant.collection, dimensions)
        yield objects, vectors
    finally:
        callbacks = ([objects.close] if objects is not None else []) + (
            [vectors.close] if vectors is not None else []
        )
        close_owned(context, callbacks)


@contextmanager
def knowledge_deletion_ports(actor, grant, *, context):
    context.remaining()
    if grant.action != "delete":
        raise ScopeDenied()
    vectors = bind_knowledge_vectors(actor, grant.collection, None)
    try:
        yield vectors
    finally:
        close_owned(context, [vectors.close])


@contextmanager
def knowledge_search_ports(actor, grant, dimensions, *, context):
    vectors = {}
    try:
        with knowledge_runtime_ports(actor, context=context) as records:
            for resource in grant.knowledge_bases:
                vectors[resource.collection] = bind_knowledge_vectors(actor, resource.collection, dimensions, writable=False)
            yield records, vectors
    finally:
        close_owned(context, [port.close for port in vectors.values()])


@contextmanager
def knowledge_chunks_ports(actor, grant, *, context):
    if not isinstance(grant, KnowledgeChunksGrant) or grant.resource_tenant_id not in {actor.tenant_id, ASSET_OWNER_TENANT_ID}:
        raise ScopeDenied()
    engine, records, vectors = record_engine(context), None, None
    try:
        scope = StorageScope('runtime', grant.resource_tenant_id, actor.user_id, {FILES, JOBS})
        records = bind_knowledge_jobs(scope, engine, knowledge_id=grant.knowledge_id, writable=False)
        vectors = bind_knowledge_vectors(actor, grant.collection, None, writable=False, resource_tenant_id=grant.resource_tenant_id)
        yield records, vectors
    finally:
        close_owned(context, ([vectors.close] if vectors is not None else []) + ([records.close] if records is not None else []) + [engine.dispose])
