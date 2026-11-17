# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read-only, revision-pinned KB content ports for explicitly authorized objects."""

from contracts.agentos_knowledge import (
    CleanseArtifact,
    KnowledgeContentGrant,
    ObjectReference,
)
from contracts.constants import environment
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import ObjectRef, Revision, StorageScope
from nexent.storage.objects import read_verified_object

from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore


def _read(actor, reference, *, role, prefix, context):
    if (
        role not in {"management", "runtime"}
        or not isinstance(reference, ObjectReference)
        or reference.space != "files"
    ):
        raise ScopeDenied()
    context.remaining()
    settings = _configured_environment()
    objects = S3ObjectStore(
        StorageScope(role, actor.tenant_id, actor.user_id, {"files"}),
        ObjectBinding(
            "files",
            settings.MINIO_DEFAULT_BUCKET,
            prefix,
            {role},
            exact_keys={reference.key},
        ),
        _configured_client,
    )
    try:
        return read_verified_object(
            objects,
            ObjectRef(reference.space, reference.key, Revision(reference.version)),
            sha256=reference.sha256,
            limit=environment.MAX_KNOWLEDGE_FILE_SIZE_BYTES,
            context=context,
        )
    finally:
        objects.close()


def read_knowledge_manifest(actor, reference, *, context):
    return CleanseArtifact.model_validate_json(
        _read(
            actor,
            reference,
            role="management",
            prefix=actor.tenant_id + "/",
            context=context,
        )
    )


def read_knowledge_content(actor, grant, *, context, role="runtime"):
    if not isinstance(grant, KnowledgeContentGrant):
        raise ScopeDenied()
    return _read(
        actor,
        grant.object_ref,
        role=role,
        prefix=actor.tenant_id + "/" if grant.image_ref is not None else "",
        context=context,
    )
