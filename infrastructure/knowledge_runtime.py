# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned Runtime-only record ports; Management metadata is obtained over AgentOS."""

from contextlib import contextmanager

from nexent.storage.models import StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_jobs import FILES, JOBS, bind_knowledge_jobs


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
