# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exact temporary source and pinned artifact ports for Runtime text cleansing."""

import re

from contracts.agentos_knowledge import (
    FileCleanseLookup,
    ObjectReference,
    cleanse_output_prefix,
)
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import ObjectRef, StorageScope

from infrastructure.object_storage.composition import (
    _configured_client,
    _configured_environment,
)
from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore


def bind_text_stage(actor, run_id, nonce, filename):
    FileCleanseLookup(run_id=run_id, job_id=nonce)
    if (
        not filename
        or filename in {".", ".."}
        or any(char in filename for char in ("/", "\\", "\x00"))
    ):
        raise ScopeDenied()
    key = f"workspace/{actor.user_id}/{run_id}/outputs/analysis/{nonce}/{filename}"
    ObjectReference(space="files", key=key, version="validation", sha256="0" * 64)
    settings = _configured_environment()
    objects = S3ObjectStore(
        StorageScope("runtime", actor.tenant_id, actor.user_id, {"files"}),
        ObjectBinding(
            "files",
            settings.MINIO_DEFAULT_BUCKET,
            "",
            {"runtime"},
            writable=True,
            exact_keys={key},
        ),
        _configured_client,
    )
    return objects, ObjectRef("files", key)


def bind_text_artifact(actor, lookup, source, artifact):
    prefix = re.escape(cleanse_output_prefix(lookup))
    if (
        artifact.space != "files"
        or source.space != "files"
        or not artifact.key.endswith("/" + artifact.sha256 + ".json")
        or not re.fullmatch(
            prefix + r"artifacts/" + source.sha256 + r"/[0-9a-f]{64}\.json",
            artifact.key,
        )
    ):
        raise ScopeDenied()
    settings = _configured_environment()
    return S3ObjectStore(
        StorageScope("runtime", actor.tenant_id, actor.user_id, {"files"}),
        ObjectBinding(
            "files",
            settings.MINIO_DEFAULT_BUCKET,
            actor.tenant_id + "/",
            {"runtime"},
            exact_keys={artifact.key},
        ),
        _configured_client,
    )
