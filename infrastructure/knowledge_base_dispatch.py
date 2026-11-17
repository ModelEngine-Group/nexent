# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own the bounded read-only handle for existing KB cleanup discovery."""

from contextlib import contextmanager

from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.rdb.knowledge_base_dispatch import bind_base_dispatch


@contextmanager
def base_dispatch_ports(*, context):
    engine, records = record_engine(context), None
    try:
        records = bind_base_dispatch(engine)
        yield records
    finally:
        close_owned(context, ([records.close] if records is not None else []) + [engine.dispose])
