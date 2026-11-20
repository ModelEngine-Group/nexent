# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only ObjectStore adapter for the SDK analysis input loader."""

from io import BytesIO
from time import monotonic
from uuid import uuid4

from nexent.storage.errors import ScopeDenied, StorageError
from nexent.storage.models import (
    Cancellation,
    ObjectRef,
    OperationContext,
    StorageScope,
)

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.exact import ExactKeyObjectStore, opaque_key
from infrastructure.object_storage.port import ObjectBinding
from infrastructure.object_storage.read_access import can_read_object

_READ_ROLES = frozenset({"management", "runtime"})
_READ_CHUNK_BYTES = 1024 * 1024


class AnalysisFileStorage:
    def __init__(self, actor: ServicePrincipal, *, role: str, cancelled: Cancellation | None = None):
        self._actor = actor
        self._role = role
        self._cancelled = cancelled

    def get_file_stream(self, object_name: str, bucket: str) -> tuple[bool, BytesIO | str]:
        """Load the bytes the SDK needs while the provider stream is still owned here."""
        context = OperationContext(
            f"analysis-file-read-{uuid4().hex}", monotonic() + 60, cancelled=self._cancelled,
        )
        try:
            key = opaque_key(object_name)
            actor = self._actor
            if not can_read_object(key, actor.user_id, actor.tenant_id):
                raise ScopeDenied()
            if bucket != _configured_environment().MINIO_DEFAULT_BUCKET:
                raise ScopeDenied()
            store = ExactKeyObjectStore(
                StorageScope(self._role, actor.tenant_id, actor.user_id, {"files"}),
                ObjectBinding("files", bucket, "", _READ_ROLES, exact_keys={key}),
                _configured_client,
            )
            with BytesIO() as contents, store.open_read(ObjectRef("files", key), context=context) as reader:
                while chunk := reader.read(_READ_CHUNK_BYTES):
                    contents.write(chunk)
                data = contents.getvalue()
        except StorageError as error:
            return False, str(error)
        return True, BytesIO(data)
