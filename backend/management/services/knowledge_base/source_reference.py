# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Normalize source identities without reading an object or database."""

from urllib.parse import urlparse

from contracts.constants.constants import ASSET_OWNER_ATTACHMENTS_PREFIX
from contracts.constants.environment import MINIO_DEFAULT_BUCKET
from contracts.knowledge import StorageObjectReference


def resolve_storage_reference(path_or_url: str | None) -> StorageObjectReference | None:
    """Normalize supported KB source paths to a bucket and object key."""
    value = (path_or_url or "").strip()
    if not value:
        return None

    if value.startswith("s3://"):
        parsed = urlparse(value)
        object_name = parsed.path.lstrip("/")
        if parsed.netloc and object_name:
            return StorageObjectReference(parsed.netloc, object_name)
        return None

    if value.startswith("/"):
        bucket_name, separator, object_name = value.lstrip("/").partition("/")
        if separator and bucket_name and object_name:
            return StorageObjectReference(bucket_name, object_name)
        return None

    source_prefixes = (
        "knowledge_base/",
        f"{ASSET_OWNER_ATTACHMENTS_PREFIX}/",
    )
    if value.startswith(source_prefixes) and MINIO_DEFAULT_BUCKET:
        return StorageObjectReference(MINIO_DEFAULT_BUCKET, value)
    return None
