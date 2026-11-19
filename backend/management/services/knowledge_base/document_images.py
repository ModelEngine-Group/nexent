# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorize legacy document image keys before exact, read-only StorageInterface I/O."""

from contracts.constants import environment
from nexent.multi_modal.utils import parse_s3_url
from nexent.storage.errors import InvalidInput, NotFound

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.file_processing.image_sources import (
    pin_object_image,
)
from infrastructure.object_storage.read_access import validate_s3_url_access


def _authorized_url(url, actor, *, context):
    context.remaining()
    if not isinstance(actor, ServicePrincipal):
        raise InvalidInput()
    if not isinstance(url, str) or not url:
        raise InvalidInput()
    if url.startswith(("s3://", "s3:/", "/")):
        bucket, key = parse_s3_url(url)
    elif ":" not in url:
        bucket, key = environment.MINIO_DEFAULT_BUCKET, url
    else:
        raise InvalidInput()
    if bucket != environment.MINIO_DEFAULT_BUCKET:
        raise InvalidInput()
    validate_s3_url_access(key, actor.user_id, actor.tenant_id)
    return f"s3://{bucket}/{key}"


def pin_document_image(url, actor, *, context):
    address = _authorized_url(url, actor, context=context)
    try:
        return pin_object_image(address, user_id=actor.user_id, tenant_id=actor.tenant_id, context=context)
    except NotFound as error:
        raise FileNotFoundError(f"Unable to fetch file from URL: {url}") from error
