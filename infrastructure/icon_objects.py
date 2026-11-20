# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind a single Management-generated icon key for a write."""

from contextlib import contextmanager

from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.exact import ExactKeyObjectStore
from infrastructure.object_storage.port import ObjectBinding
from infrastructure.rdb.composition import close_owned


@contextmanager
def icon_write_port(key, *, context):
    if not key.startswith(('agent-icons/', 'agent-repository-icons/')):
        raise ScopeDenied()
    bucket = _configured_environment().MINIO_DEFAULT_BUCKET
    scope = StorageScope('management', None, 'management.icon.write', {'files'}, system=True)
    binding = ObjectBinding('files', bucket, '', {'management'}, writable=True,
                            allow_system=True, exact_keys={key})
    store = ExactKeyObjectStore(scope, binding, _configured_client)
    try:
        context.remaining()
        yield store
    finally:
        close_owned(context, [store.close])
