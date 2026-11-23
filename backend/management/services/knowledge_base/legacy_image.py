# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize the exact historical ES hit before accessing its pinned attachment."""

import re

from contracts.agentos_knowledge import KnowledgeLegacyImageRequest
from contracts.constants import environment
from management.services.knowledge_base.chunks_authorization import (
    chunks_resource_grant,
)
from management.services.knowledge_base.file_reader import KnowledgeFileReader
from nexent.storage.errors import ScopeDenied

from infrastructure.file_processing.image_sources import pin_object_image
from infrastructure.knowledge_content import read_legacy_attachment
from infrastructure.vdb.native_knowledge import read_native_legacy_image


def _authorized_image(locator, actor, *, context):
    row = KnowledgeFileReader().knowledge(None, actor, knowledge_id=locator.knowledge_id, context=context)
    resource = chunks_resource_grant(row)
    url, filename = read_native_legacy_image(actor, resource, locator, context=context)
    base = f"s3://{environment.MINIO_DEFAULT_BUCKET}/"
    if not url.startswith(base):
        raise ScopeDenied()
    key = url[len(base):]
    if (not re.fullmatch(r"images_in_attachments/[A-Za-z0-9_./-]+\.(?:png|jpe?g|gif|webp|bmp|tiff?)", key, flags=re.I)
        or any(part in {"", ".", ".."} for part in key.split("/"))):
        raise ScopeDenied()
    return url, filename if isinstance(filename, str) and filename else key.rsplit("/", 1)[1]


def pin_legacy_image(locator, actor, *, context):
    url, _ = _authorized_image(locator, actor, context=context)
    reference = pin_object_image(url, user_id=actor.user_id, tenant_id=actor.tenant_id, context=context,
                                 max_bytes=environment.MAX_KNOWLEDGE_FILE_SIZE_BYTES)
    return KnowledgeLegacyImageRequest(**locator.model_dump(), image_ref=reference)


def authorize_legacy_image(request, actor, *, context):
    if not isinstance(request, KnowledgeLegacyImageRequest):
        raise ScopeDenied()
    url, filename = _authorized_image(request, actor, context=context)
    if url != f"s3://{environment.MINIO_DEFAULT_BUCKET}/{request.image_ref.key}" or request.image_ref.space != "files":
        raise ScopeDenied()
    return filename


def authorize_legacy_image_access(payload, actor, *, context):
    request = payload.root
    if isinstance(request, KnowledgeLegacyImageRequest):
        authorize_legacy_image(request, actor, context=context)
        return request
    return pin_legacy_image(request, actor, context=context)


def fetch_legacy_image(request, actor, *, context):
    filename = authorize_legacy_image(request, actor, context=context)
    data = read_legacy_attachment(actor, request, context=context)
    if authorize_legacy_image(request, actor, context=context) != filename:
        raise ScopeDenied()
    return data, filename
