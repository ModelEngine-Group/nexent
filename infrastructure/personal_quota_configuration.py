# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind current identity, permission metadata and authorized tenant quota records."""

from contextlib import contextmanager

from infrastructure.knowledge_collection_metadata import bind_collection_permissions
from infrastructure.quota_write import bind_quota_write_records
from infrastructure.rdb.composition import close_owned, record_engine
from infrastructure.tenant_quota_read import bind_quota_identity


@contextmanager
def personal_quota_configuration_ports(actor, *, context, writable=False):
    engine, owned = record_engine(context, connections=2 if writable else 1), []
    try:
        identity = bind_quota_identity(actor, engine)
        owned.append(identity)
        permissions = bind_collection_permissions(actor, engine)
        owned.append(permissions)

        def records(tenant):
            port = bind_quota_write_records(actor, tenant, engine, writable=writable)
            owned.append(port)
            return port

        yield identity, permissions, records
    finally:
        close_owned(context, [port.close for port in reversed(owned)] + [engine.dispose])
