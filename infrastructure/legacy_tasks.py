# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prove exact historical index ownership before opening legacy Redis read ports."""

from contextlib import contextmanager

from contracts.constants import environment
from contracts.knowledge_maintenance import LEGACY_INDEX_OWNER, LEGACY_TASKS
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.legacy_index_owner import bind_legacy_index_owner
from infrastructure.redis.legacy_tasks import LegacyTaskRecords


@contextmanager
def legacy_task_records(actor, knowledge_id, index_name, *, known_tasks, context, cancellation_scope=None):
    engine, ownership, records = record_engine(context), None, None
    try:
        ownership = bind_legacy_index_owner(actor, knowledge_id, index_name, engine)
        row = ownership.get(LEGACY_INDEX_OWNER, index_name, context=context)
        if row is None or row['owner_count'] != 1 or row['selected_owner_count'] != 1: raise ScopeDenied()
        if not environment.REDIS_BACKEND_URL or not environment.REDIS_URL: raise InvalidInput()
        records = LegacyTaskRecords(StorageScope('management', actor.tenant_id, actor.user_id, {LEGACY_TASKS}),
            index_name, known_tasks, backend_url=environment.REDIS_BACKEND_URL, general_url=environment.REDIS_URL,
            cancellation_scope=cancellation_scope)
        yield records
    finally:
        close_owned(context, ([records.close] if records else []) + ([ownership.close] if ownership else []) + [engine.dispose])
