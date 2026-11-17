# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime reads pinned sources, manifests and their declared image revisions."""

import re
from contextlib import contextmanager

from contracts.agentos_knowledge import CleanseArtifact, KnowledgeFileGrant
from contracts.knowledge_cleanse import knowledge_artifact_prefix
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


class PinnedImages:
    """Only manifest-declared image revisions may cross this read-only boundary."""

    def __init__(self, objects, references):
        self.scope = objects.scope
        self._objects, self._references, self._closed = objects, frozenset(references), False

    def _check(self, ref):
        if self._closed or ref not in self._references:
            raise ScopeDenied()

    def stat(self, ref, *, context):
        self._check(ref)
        return self._objects.stat(ref, context=context)

    def open_read(self, ref, *, context):
        self._check(ref)
        return self._objects.open_read(ref, context=context)

    def close(self):
        if not self._closed:
            self._closed = True
            self._objects.close()


@contextmanager
def bind_knowledge_image_objects(actor, grant, artifact, *, context):
    if (not isinstance(grant, KnowledgeFileGrant) or grant.action != "execute"
            or grant.source is None or grant.source.space != "files"
            or not isinstance(artifact, CleanseArtifact) or grant.source != artifact.source
            or grant.parser_version != artifact.parser_version):
        raise ScopeDenied()
    references = []
    try:
        prefix = knowledge_artifact_prefix(grant, grant.artifact)
    except (TypeError, ValueError):
        raise ScopeDenied() from None
    for block in artifact.blocks:
        if block.kind != "image":
            continue
        ref = block.object_ref
        if (ref.space != "files" or not re.fullmatch(
                re.escape(prefix) + "images/" + re.escape(artifact.source.sha256) + "/" + re.escape(ref.sha256)
                + r"\.(?:png|jpg|jpeg|gif|webp|bmp|tiff)", ref.key)):
            raise ScopeDenied()
        references.append(ObjectRef(ref.space, ref.key, Revision(ref.version)))
    settings = _configured_environment()
    objects = S3ObjectStore(
        StorageScope("runtime", actor.tenant_id, actor.user_id, {"files"}),
        ObjectBinding("files", settings.MINIO_DEFAULT_BUCKET, actor.tenant_id + "/", {"runtime"},
                      exact_keys={ref.key for ref in references}), _configured_client,
    )
    pinned = PinnedImages(objects, references)
    try:
        context.remaining()
        yield pinned
    finally:
        pinned.close()


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
