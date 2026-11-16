# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned tenant-scoped handles for KB cleansing admission and authorization."""

from contextlib import contextmanager

from nexent.storage.models import StorageScope

from infrastructure.rdb.cleanse_jobs import DATASET, bind_cleanse_jobs
from infrastructure.rdb.cleanse_resources import TABLES, bind_cleanse_resources
from infrastructure.rdb.composition import close_owned, record_engine


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
