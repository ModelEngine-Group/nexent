# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned tenant-scoped handles for KB cleansing admission and authorization."""

from contextlib import contextmanager

from contracts.knowledge_cleanse import CLEANSE_HANDLER, CLEANSE_QUEUE_NAMESPACE
from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_dispatch import bind_cleanse_dispatch
from infrastructure.rdb.cleanse_jobs import DATASET, bind_cleanse_jobs
from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.redis.kv import RedisKeyValueConfig, RedisKeyValueStore
from infrastructure.storage.work_queue import KombuWorkQueue, QueueBinding


@contextmanager
def knowledge_cleanse_ports(tenant_id, user_id, *, context):
    job_scope = StorageScope("management", tenant_id, user_id, {DATASET})
    resource_scope = StorageScope("management", tenant_id, user_id, set(TABLES))
    engine = record_engine(context)
    jobs = resources = None
    try:
        jobs = bind_cleanse_jobs(job_scope, engine)
        resources = bind_cleanse_resources(resource_scope, engine)
        yield jobs, resources
    finally:
        callbacks = [engine.dispose]
        if jobs is not None:
            callbacks.insert(0, jobs.close)
        if resources is not None:
            callbacks.insert(0, resources.close)
        close_owned(context, callbacks)


@contextmanager
def cleanse_dispatch_ports(*, context):
    engine = record_engine(context)
    records = None
    try:
        records = bind_cleanse_dispatch(engine)
        yield records
    finally:
        callbacks = [engine.dispose]
        if records is not None:
            callbacks.insert(0, records.close)
        close_owned(context, callbacks)


@contextmanager
def knowledge_resource_ports(tenant_id, user_id, *, context):
    engine, resources = record_engine(context), None
    try:
        namespaces = set(TABLES) - {"cleanse_files", "knowledge_file_history"}
        resources = bind_cleanse_resources(StorageScope("management", tenant_id, user_id, namespaces), engine)
        yield resources
    finally:
        close_owned(context, ([resources.close] if resources is not None else []) + [engine.dispose])


def queue_environment():
    from contracts.constants import environment

    return environment


@contextmanager
def knowledge_cleanse_queue(tenant_id, owner_id, *, context):
    environment = queue_environment()
    context.remaining()
    scope = StorageScope("management", tenant_id, owner_id, {CLEANSE_QUEUE_NAMESPACE})
    config = RedisKeyValueConfig(environment.REDIS_BACKEND_URL, CLEANSE_QUEUE_NAMESPACE)
    binding = QueueBinding(
        CLEANSE_QUEUE_NAMESPACE,
        environment.REDIS_URL,
        {"management"},
        {CLEANSE_HANDLER},
        visibility_timeout=7200,
    )
    kv = RedisKeyValueStore(config, scope, namespace=CLEANSE_QUEUE_NAMESPACE)
    queue = None
    try:
        queue = KombuWorkQueue(scope, binding, kv)
        yield queue
    finally:
        callbacks = [kv.close]
        if queue is not None:
            callbacks.insert(0, queue.close)
        close_owned(context, callbacks)
