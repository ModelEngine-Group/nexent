# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned snapshot record handles for ledger business queries and exact ownership lookup."""

from contextlib import contextmanager

from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.storage_ledger import (
    HISTORY,
    LEDGER,
    bind_ledger_lookup,
    bind_ledger_records,
)


@contextmanager
def ledger_record_ports(tenant_id, actor_id, *, context, identity=None):
    engine = record_engine(context, snapshot=True)
    records = None
    try:
        if identity is not None:
            if tenant_id is not None:
                raise ScopeDenied()
            bucket, key, include_deleted = identity
            records = bind_ledger_lookup(
                bucket, key, engine, include_deleted=include_deleted
            )
        else:
            records = bind_ledger_records(
                StorageScope("management", tenant_id, actor_id, {LEDGER, HISTORY}),
                engine,
            )
        yield records
    finally:
        callbacks = [engine.dispose]
        if records is not None:
            callbacks.insert(0, records.close)
        close_owned(context, callbacks)
