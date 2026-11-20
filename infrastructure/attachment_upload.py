# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Publish a single attachment key selected by the upload caller."""

from time import monotonic
from uuid import uuid4

from nexent.storage.models import ObjectRef, OperationContext, StorageScope

from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.exact import ExactKeyObjectStore
from infrastructure.object_storage.port import ObjectBinding
from infrastructure.rdb.composition import close_owned


def put_attachment(stream, object_name, bucket, *, content_type, size):
    bucket = bucket or _configured_environment().MINIO_DEFAULT_BUCKET
    context = OperationContext(f'attachment-upload-{uuid4().hex}', monotonic() + 120)
    scope = StorageScope('management', None, 'management.attachment.upload', {'files'}, system=True)
    binding = ObjectBinding('files', bucket, '', {'management'}, writable=True,
                            allow_system=True, exact_keys={object_name})
    store = ExactKeyObjectStore(scope, binding, _configured_client)
    try:
        store.put(ObjectRef('files', object_name), stream, content_type=content_type,
                  size=size, context=context)
        return f'/{bucket}/{object_name}'
    finally:
        close_owned(context, [store.close])
