# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Object-read scope shared by Management and Runtime tool adapters."""

import logging
from urllib.parse import quote

from contracts.constants.constants import ASSET_OWNER_ATTACHMENTS_PREFIX, ASSET_OWNER_TENANT_ID

logger = logging.getLogger(__name__)


def can_read_object(object_name: str, user_id: str, tenant_id: str | None) -> bool:
    if not user_id:
        return False
    if object_name.startswith(ASSET_OWNER_ATTACHMENTS_PREFIX):
        return tenant_id == ASSET_OWNER_TENANT_ID
    if object_name.startswith(("knowledge_base/", "images_in_attachments/")):
        return True
    if object_name.startswith("workspace/"):
        parts = object_name.split("/")
        return len(parts) >= 5 and parts[1] == user_id and parts[3] == "outputs"
    if object_name.startswith((f"attachments/{user_id}/", f"skill-files/{user_id}/")):
        return True
    return object_name.startswith("attachments/") and "/" not in object_name.removeprefix("attachments/")


def require_s3_read_access(urls: list[str], user_id: str, tenant_id: str) -> None:
    from nexent.multi_modal.utils import parse_s3_url

    for url in urls:
        try:
            _, object_name = parse_s3_url(url)
        except ValueError as exc:
            raise PermissionError("Invalid S3 URL") from exc
        if not can_read_object(object_name, user_id, tenant_id):
            raise PermissionError("Object is outside the run's read scope")


def build_attachment_proxy_url(presigned_url: str, northbound_url: str) -> str:
    if not presigned_url:
        return ""
    return f"{northbound_url}/nb/v1/file/fetch?presigned_url={quote(presigned_url, safe='')}"


def validate_s3_url_access(
    object_name: str,
    user_id: str | None,
    caller_tenant_id: str | None = None,
) -> None:
    """
    Validate if user has permission to access the S3 URL.

    Args:
        object_name: File object name in storage (extracted from S3 URL)
        user_id: Current user ID

    Raises:
        PermissionError: If user doesn't have permission to access the file
    """
    if not user_id:
        raise PermissionError("User authentication required to access files")

    if not can_read_object(object_name, user_id, caller_tenant_id):
        logger.warning(
            f"[validate_s3_url_access] Access denied: object_name={object_name}, user_id={user_id}")
        raise PermissionError(
            f"Access denied: You don't have permission to access this file ({object_name})")


def validate_urls_access(
    urls: list[str],
    user_id: str | None,
    caller_tenant_id: str | None = None,
) -> None:
    """
    Validate if user has permission to access the given URLs.

    Supports S3 URLs (s3://bucket/key or /bucket/key format).

    Args:
        urls: List of URLs to validate (S3, HTTP, or HTTPS)
        user_id: Current user ID

    Raises:
        PermissionError: If user doesn't have permission to access any of the files
    """
    from nexent.multi_modal.utils import parse_s3_url

    if not urls:
        return

    for url in urls:
        if not url:
            continue

        # Only validate S3 URLs (MinIO storage)
        # HTTP/HTTPS URLs are external resources and are not subject to MinIO access control
        if url.startswith("s3://"):
            try:
                _, object_name = parse_s3_url(url)
                validate_s3_url_access(object_name, user_id, caller_tenant_id)
            except ValueError as e:
                logger.warning(
                    f"[validate_urls_access] Failed to parse S3 URL: {url}, error: {e}")
                raise PermissionError(f"Invalid S3 URL format: {url}")
        elif url.startswith("/") and not url.startswith("//"):
            # Handle /bucket/key format (absolute path style)
            parts = url.strip("/").split("/", 1)
            if len(parts) == 2:
                bucket, object_name = parts
                validate_s3_url_access(object_name, user_id, caller_tenant_id)
