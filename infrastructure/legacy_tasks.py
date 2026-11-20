# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prove exact historical index ownership before opening legacy Redis read ports."""

from contextlib import contextmanager
from functools import partial

from contracts.constants import environment
from contracts.knowledge_maintenance import (
    BROKER_INVENTORY,
    LEGACY_INDEX_OWNER,
    LEGACY_INGESTION_INVENTORY,
    LEGACY_TASK_REFERENCES,
    LEGACY_TASKS,
)
from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.legacy_index_owner import bind_legacy_index_owner
from infrastructure.rdb.legacy_ingestion_inventory import (
    bind_legacy_ingestion_inventory,
    bind_legacy_task_references,
    legacy_task_reference_counts,
)
from infrastructure.redis.legacy_broker import LegacyBrokerRecords
from infrastructure.redis.legacy_tasks import LegacyTaskRecords
from infrastructure.tenant_quota_read import bind_quota_identity


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


@contextmanager
def legacy_broker_ports(actor, *, context):
    engine, identity, broker, inventory, references = record_engine(context), None, None, None, None
    try:
        identity = bind_quota_identity(actor, engine)
        references = bind_legacy_task_references(
            StorageScope("management", None, actor.user_id, {LEGACY_TASK_REFERENCES}, system=True), engine,
        )
        broker = LegacyBrokerRecords(
            StorageScope("management", actor.tenant_id, actor.user_id, {BROKER_INVENTORY}),
            environment.REDIS_URL, result_url=environment.REDIS_BACKEND_URL,
            reference_counts=partial(legacy_task_reference_counts, references),
        )
        scope = StorageScope(
            "management", None, actor.user_id, {LEGACY_INGESTION_INVENTORY}, system=True,
        )
        inventory = bind_legacy_ingestion_inventory(scope, engine)
        yield identity, broker, inventory
    finally:
        close_owned(context, [port.close for port in (inventory, broker, references, identity) if port is not None] + [engine.dispose])
