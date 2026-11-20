# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""ObjectStore adapter for the Runtime workspace upload and download tools."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
from uuid import uuid4

from nexent.storage.errors import InvalidInput, ScopeDenied, StorageError
from nexent.storage.models import ObjectRef, OperationContext, StorageScope

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.exact import ExactKeyObjectStore, opaque_key
from infrastructure.object_storage.port import ObjectBinding
from infrastructure.object_storage.read_access import can_read_object

_MAX_FILE_BYTES = 100 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024


def _valid_segment(value: str | None) -> bool:
    return bool(value and value not in {".", ".."} and not any(c in value for c in "/\\\x00"))


class RunFileStorage:
    """Expose the SDK tool's three file operations through exact object grants."""

    def __init__(self, actor: ServicePrincipal, run_id: str | None):
        self._actor = actor
        self._run_id = run_id

    @property
    def default_bucket(self) -> str:
        return _configured_environment().MINIO_DEFAULT_BUCKET

    def _object(self, key: str, bucket: str | None = None, *, writable: bool = False):
        key = opaque_key(key)
        actor = self._actor
        if writable:
            prefix = f"workspace/{actor.user_id}/{self._run_id}/outputs/"
            if (
                not _valid_segment(actor.user_id) or not _valid_segment(self._run_id)
                or not key.startswith(prefix)
                or not all(_valid_segment(part) for part in key[len(prefix):].split("/"))
            ):
                raise ScopeDenied()
        elif not can_read_object(key, actor.user_id, actor.tenant_id):
            raise ScopeDenied()
        default_bucket = self.default_bucket
        if bucket and bucket != default_bucket:
            raise ScopeDenied()
        return ExactKeyObjectStore(
            StorageScope("runtime", actor.tenant_id, actor.user_id, {"files"}),
            ObjectBinding("files", default_bucket, "", {"runtime"}, writable=writable, exact_keys={key}),
            _configured_client,
        ), ObjectRef("files", key)

    def get_file_size(self, object_name: str, bucket: str | None = None) -> int:
        context = OperationContext(f"tool-file-stat-{uuid4().hex}", monotonic() + 5)
        try:
            store, ref = self._object(object_name, bucket)
            return store.stat(ref, context=context).size
        except ScopeDenied:
            raise
        except StorageError:
            return 0

    def download_file(self, object_name: str, file_path: str, bucket: str | None = None) -> tuple[bool, str]:
        context = OperationContext(f"tool-file-read-{uuid4().hex}", monotonic() + 120)
        destination = Path(file_path)
        staged = None
        try:
            store, ref = self._object(object_name, bucket)
            with (
                store.open_read(ref, context=context) as reader,
                NamedTemporaryFile(dir=destination.parent, delete=False) as stream,
            ):
                staged = Path(stream.name)
                size = 0
                while chunk := reader.read(_CHUNK_BYTES):
                    size += len(chunk)
                    if size > _MAX_FILE_BYTES:
                        raise InvalidInput(operation_id=context.operation_id)
                    stream.write(chunk)
            context.remaining()
            staged.replace(destination)
            staged = None
        except (OSError, StorageError) as error:
            return False, str(error)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
        return True, f"File downloaded successfully to {file_path}"

    def upload_file(self, file_path: str, object_name: str) -> tuple[bool, str]:
        context = OperationContext(f"tool-file-put-{uuid4().hex}", monotonic() + 120)
        try:
            store, ref = self._object(object_name, writable=True)
            with Path(file_path).open("rb") as stream:
                size = os.fstat(stream.fileno()).st_size
                if size > _MAX_FILE_BYTES:
                    raise InvalidInput(operation_id=context.operation_id)
                store.put(ref, stream, size=size, content_type="application/octet-stream", context=context)
        except (OSError, StorageError) as error:
            return False, str(error)
        return True, f"/{self.default_bucket}/{object_name}"
