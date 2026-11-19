# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own one exact, Management-authorized object handle for deletion."""

from contextlib import contextmanager

from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.deletion import ExactObjectDeletionStore
from infrastructure.object_storage.port import ObjectBinding
from infrastructure.rdb.composition import close_owned


@contextmanager
def file_object_ports(actor, reference, *, context):
    if reference.bucket_name != _configured_environment().MINIO_DEFAULT_BUCKET:
        raise ScopeDenied()
    objects = ExactObjectDeletionStore(StorageScope('management', actor.tenant_id, actor.user_id, {'files'}),
        ObjectBinding('files', reference.bucket_name, '', {'management'}, writable=True, exact_keys={reference.object_name}),
        _configured_client)
    try:
        context.remaining()
        yield objects
    finally:
        close_owned(context, [objects.close])
