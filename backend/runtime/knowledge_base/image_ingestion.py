# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Materialize verified image inputs without persisting transport bytes."""

import base64
import json

from nexent.storage.errors import CapabilityUnsupported, InvalidInput, ScopeDenied
from nexent.storage.models import ObjectRef, Revision
from nexent.storage.objects import read_verified_object


def image_documents(artifact, factory, *, actor, limit, context):
    blocks = [block for block in artifact.blocks if block.kind == "image"]
    if not blocks:
        return []
    if factory is None:
        raise CapabilityUnsupported()
    documents = []
    with factory(artifact, context=context) as objects:
        scope = objects.scope
        if (scope.system or scope.service_role != "runtime" or scope.tenant_id != actor.tenant_id
                or scope.actor_id != actor.user_id or "files" not in scope.namespaces):
            raise ScopeDenied()
        for block in blocks:
            context.remaining()
            ref = block.object_ref
            extension = ref.key.rsplit(".", 1)[-1].lower()
            if extension not in {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"}:
                raise InvalidInput()
            raw = read_verified_object(objects, ObjectRef(ref.space, ref.key, Revision(ref.version)),
                                       sha256=ref.sha256, limit=limit, context=context)
            mime = "image/jpeg" if extension in {"jpg", "jpeg"} else "image/" + extension
            documents.append({
                "content": json.dumps({"image_ref": ref.model_dump(), "position": block.location}, ensure_ascii=False),
                "metadata": block.location,
                "_image_ref": ref.model_dump(),
                "_image_input": f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"),
            })
    return documents
