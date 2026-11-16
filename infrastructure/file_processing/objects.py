# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Separate an exact immutable source grant from tenant-partitioned outputs."""

import re

from contracts.agentos_knowledge import ObjectReference
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
    bind_source_objects,
)
from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore
from infrastructure.rdb.composition import close_owned


class CleanseObjects:
    """The parser receives only pinned read and content-addressed put operations."""

    def __init__(self, source, inputs, outputs, *, context):
        self.source = source
        self._inputs = inputs
        self._outputs = outputs
        self.context = context
        self._closed = False
        self._output = re.compile(
            rf"(?:artifacts/{source.sha256}/[0-9a-f]{{64}}\.json|"
            rf"images/{source.sha256}/[0-9a-f]{{64}}\.(?:png|jpg|jpeg|gif|webp|bmp|tiff))"
        )

    def _read(self, ref):
        if (
            self._closed
            or ref.space != self.source.space
            or ref.key != self.source.key
            or ref.version is None
            or ref.version.value != self.source.version
        ):
            raise ScopeDenied()

    def stat(self, ref, *, context):
        self._read(ref)
        return self._inputs.stat(ref, context=context)

    def open_read(self, ref, *, context):
        self._read(ref)
        return self._inputs.open_read(ref, context=context)

    def put(self, ref, stream, *, content_type, size, context):
        if (
            self._closed
            or ref.space != self.source.space
            or ref.version is not None
            or self._output.fullmatch(ref.key) is None
        ):
            raise ScopeDenied()
        return self._outputs.put(
            ref, stream, content_type=content_type, size=size, context=context
        )

    def close(self):
        if not self._closed:
            self._closed = True
            close_owned(self.context, [self._inputs.close, self._outputs.close])


def bind_cleanse_objects(tenant_id, user_id, source, *, context):
    if not isinstance(source, ObjectReference) or source.space != "files":
        raise ScopeDenied()
    environment = _configured_environment()
    scope = StorageScope("management", tenant_id, user_id, {"files"})
    inputs = bind_source_objects(
        tenant_id, user_id, source.key, environment.MINIO_DEFAULT_BUCKET, writable=False
    )
    try:
        outputs = S3ObjectStore(
            scope,
            ObjectBinding(
                "files",
                environment.MINIO_DEFAULT_BUCKET,
                "",
                {"management"},
                writable=True,
            ),
            _configured_client,
        )
        return CleanseObjects(source, inputs, outputs, context=context)
    except BaseException:
        inputs.close()
        raise
