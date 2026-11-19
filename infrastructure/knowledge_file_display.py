# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bind exact display-only keys selected from an already authorized KB file list."""

from contextlib import contextmanager

from contracts.constants import environment
from nexent.storage.errors import InvalidInput
from nexent.storage.models import ObjectRef, StorageScope

from infrastructure.object_storage.composition import _configured_client
from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore
from infrastructure.rdb.composition import close_owned


@contextmanager
def knowledge_file_display_objects(actor, key, *, context):
    context.remaining()
    if not isinstance(key, str) or not key:
        raise InvalidInput()
    # Preserve persisted source address forms; the caller has already authorized
    # this exact address through the KB. No request-selected bucket is accepted.
    bucket = environment.MINIO_DEFAULT_BUCKET
    if key.startswith("s3://"):
        parts = key[5:].split("/", 1)
        bucket, key = parts[0] or bucket, parts[1] if len(parts) > 1 else ""
    elif key.startswith("/"):
        parts = key.lstrip("/").split("/", 1)
        bucket, key = parts[0] or bucket, parts[1] if len(parts) > 1 else ""
    if not bucket or not key:
        raise InvalidInput()
    objects = S3ObjectStore(
        StorageScope("management", actor.tenant_id, actor.user_id, {"files"}),
        ObjectBinding(
            "files",
            bucket,
            "",
            frozenset({"management"}),
            writable=False,
            exact_keys=frozenset({key}),
        ),
        _configured_client,
    )
    try:
        yield objects, ObjectRef("files", key)
    finally:
        close_owned(context, [objects.close])
