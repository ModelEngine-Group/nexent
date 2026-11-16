# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned Runtime-only record ports; Management metadata is obtained over AgentOS."""

from contextlib import contextmanager

from nexent.storage.models import StorageScope

from infrastructure.knowledge_objects import bind_knowledge_objects
from infrastructure.knowledge_vectors import bind_knowledge_vectors
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_dispatch import bind_knowledge_dispatch
from infrastructure.rdb.knowledge_jobs import FILES, JOBS, bind_knowledge_jobs


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
