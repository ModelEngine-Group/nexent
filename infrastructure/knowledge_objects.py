# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime reads only the pinned legacy source and tenant-partitioned cleanse artifact."""

from contracts.agentos_knowledge import KnowledgeFileGrant
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import ObjectRef, Revision, StorageScope

from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore
from infrastructure.rdb.composition import close_owned


class KnowledgeObjects:
    def __init__(self, scope, grant, source, artifact, context):
        self.scope = scope
        self._source, self._artifact = source, artifact
        self._source_ref = ObjectRef(
            grant.source.space, grant.source.key, Revision(grant.source.version)
        )
        self._artifact_ref = ObjectRef(
            grant.artifact.space, grant.artifact.key, Revision(grant.artifact.version)
        )
        self._context, self._closed = context, False

    def _port(self, ref):
        if not self._closed:
            if ref == self._source_ref:
                return self._source
            if ref == self._artifact_ref:
                return self._artifact
        raise ScopeDenied()

    def stat(self, ref, *, context):
        return self._port(ref).stat(ref, context=context)

    def open_read(self, ref, *, context):
        return self._port(ref).open_read(ref, context=context)

    def close(self):
        if not self._closed:
            self._closed = True
            close_owned(self._context, [self._source.close, self._artifact.close])


def bind_knowledge_objects(actor, grant, *, context):
    if (
        not isinstance(grant, KnowledgeFileGrant)
        or grant.action != "execute"
        or grant.source is None
        or grant.artifact is None
        or grant.source.space != "files"
        or grant.artifact.space != "files"
        or grant.source == grant.artifact
    ):
        raise ScopeDenied()
    environment = _configured_environment()
    scope = StorageScope("runtime", actor.tenant_id, actor.user_id, {"files"})
    source = S3ObjectStore(
        scope,
        ObjectBinding(
            "files",
            environment.MINIO_DEFAULT_BUCKET,
            "",
            {"runtime"},
            exact_keys={grant.source.key},
        ),
        _configured_client,
    )
    try:
        artifact = S3ObjectStore(
            scope,
            ObjectBinding(
                "files",
                environment.MINIO_DEFAULT_BUCKET,
                actor.tenant_id + "/",
                {"runtime"},
                exact_keys={grant.artifact.key},
            ),
            _configured_client,
        )
        return KnowledgeObjects(scope, grant, source, artifact, context)
    except BaseException:
        source.close()
        raise
