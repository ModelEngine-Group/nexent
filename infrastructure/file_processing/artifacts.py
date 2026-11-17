# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Closed-writer cleansing artifacts: private pinned reads and exact-key cleanup only."""

import re

from contracts.agentos_knowledge import (
    FileCleanseLookup,
    KnowledgeCleanseLookup,
    cleanse_output_prefix,
)
from nexent.storage.errors import Conflict, InvalidInput, ScopeDenied
from nexent.storage.models import ObjectRef, StorageScope

from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore


class CleanseArtifacts:
    """Issued after reserving cleanup for one closed-writer private job directory."""

    def __init__(self, objects, lookup, source):
        if not isinstance(lookup, (FileCleanseLookup, KnowledgeCleanseLookup)):
            raise ScopeDenied()
        self._objects = objects
        self._space = source.space
        self._prefix = cleanse_output_prefix(lookup)
        prefix = re.escape(cleanse_output_prefix(lookup))
        self._keys = re.compile(
            rf"{prefix}(?:artifacts/{source.sha256}/[0-9a-f]{{64}}\.json|"
            rf"images/{source.sha256}/[0-9a-f]{{64}}\.(?:png|jpg|jpeg|gif|webp|bmp|tiff))"
        )
        self._closed = False

    def _check(self, ref):
        if (
            self._closed
            or ref.space != self._space
            or ref.version is None
            or not self._keys.fullmatch(ref.key)
        ):
            raise ScopeDenied()

    def stat(self, ref, *, context):
        self._check(ref)
        return self._objects.stat(ref, context=context)

    def open_read(self, ref, *, context):
        self._check(ref)
        return self._objects.open_read(ref, context=context)

    def delete(self, ref, *, context):
        self._check(ref)
        if not ref.version.value.startswith(("version:", "etag:")):
            raise InvalidInput()
        if ref.version.value.startswith("version:"):
            return self._objects.delete(ref, context=context)
        current = self._objects.stat(ObjectRef(ref.space, ref.key), context=context)
        if current.ref != ref:
            raise Conflict(operation_id=context.operation_id)
        # The admitted writer is finished and the release reservation is exclusive.
        # Unversioned MinIO has no atomic ETag delete. Do not attempt then downgrade.
        return self._objects.delete(ObjectRef(ref.space, ref.key), context=context)

    def list(self, prefix, page, *, context):
        if self._closed or prefix != self._prefix:
            raise ScopeDenied()
        result = self._objects.list(prefix, page, context=context)
        for item in result.items:
            self._check(item.ref)
        return result

    def close(self):
        if not self._closed:
            self._closed = True
            self._objects.close()


def bind_run_cleanse_artifacts(tenant_id, user_id, lookup, source, *, context):
    if not isinstance(lookup, FileCleanseLookup):
        raise ScopeDenied()
    return _bind_artifacts(tenant_id, user_id, lookup, source, context=context)


def bind_knowledge_cleanse_artifacts(tenant_id, user_id, lookup, source, *, context):
    if not isinstance(lookup, KnowledgeCleanseLookup):
        raise ScopeDenied()
    return _bind_artifacts(tenant_id, user_id, lookup, source, context=context)


def _bind_artifacts(tenant_id, user_id, lookup, source, *, context):
    context.remaining()
    cleanse_output_prefix(lookup)
    if lookup is None or source.space != "files":
        raise ScopeDenied()
    environment = _configured_environment()
    store = S3ObjectStore(
        StorageScope("management", tenant_id, user_id, {"files"}),
        ObjectBinding(
            "files", environment.MINIO_DEFAULT_BUCKET, "", {"management"}, writable=True
        ),
        _configured_client,
    )
    try:
        return CleanseArtifacts(store, lookup, source)
    except BaseException:
        store.close()
        raise
