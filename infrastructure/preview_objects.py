# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Grant only one selected preview source or one derived cache key."""

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
def preview_object_ports(object_name, *, writable=False, context):
    if type(writable) is not bool or writable and not object_name.startswith('preview/converted/'):
        raise ScopeDenied()
    bucket = _configured_environment().MINIO_DEFAULT_BUCKET
    store = ExactKeyObjectStore(StorageScope('management', None, 'office-preview', {'files'}, system=True),
        ObjectBinding('files', bucket, '', {'management'}, writable=writable, allow_system=True, exact_keys={object_name}),
        _configured_client)
    try:
        context.remaining()
        yield store
    finally:
        close_owned(context, [store.close])
