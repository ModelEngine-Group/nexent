# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from contracts.constants.constants import ASSET_OWNER_ATTACHMENTS_PREFIX
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from typing import Dict
from typing import List
from typing import Optional
from nexent.multi_modal.utils import parse_s3_url

import logging
logger = logging.getLogger('management.services.file.service')

def check_file_access(
    object_name: str,
    user_id: Optional[str],
    caller_tenant_id: Optional[str] = None,
    required_permission: str = "READ",
) -> bool:
    """
    Check if user has permission to access the file.

    Access rules:
    - knowledge_base/*: All authenticated users can read; write operations
      resolve the storage ledger and the owning knowledge-base DAC permission
    - attachments/{user_id}/*: Only the owner (user_id) can access
    - images_in_attachments/*: All authenticated users can read; writes are denied
    - workspace/{user_id}/{run_id}/outputs/*: Only the owner can access

    Args:
        object_name: File object name in storage
        user_id: Current user ID
        required_permission: READ for compatibility reads, or EDIT/DELETE for writes

    Returns:
        True if access is allowed, False otherwise
    """
    if not user_id:
        return False

    normalized_permission = str(required_permission or "READ").upper()
    is_read = normalized_permission in {"READ", "READ_ONLY"}

    if object_name.startswith(ASSET_OWNER_ATTACHMENTS_PREFIX):
        if is_read:
            return caller_tenant_id == ASSET_OWNER_TENANT_ID
        from management.services.knowledge_base.storage import resolve_storage_object_access

        return resolve_storage_object_access(
            object_name=object_name,
            user_id=user_id,
            tenant_id=caller_tenant_id,
            required_permission=normalized_permission,
        )

    if object_name.startswith("knowledge_base/"):
        # Preserve the established compatibility policy for source reads.
        if is_read:
            return True
        from management.services.knowledge_base.storage import resolve_storage_object_access

        return resolve_storage_object_access(
            object_name=object_name,
            user_id=user_id,
            tenant_id=caller_tenant_id,
            required_permission=normalized_permission,
        )

    if object_name.startswith("images_in_attachments/"):
        # Extracted image files used by knowledge-base image chunks.
        # Keep them readable for authenticated users to avoid broken image citations.
        return is_read

    if object_name.startswith("skill-files/"):
        # Generated documents are private to the uploader and must stay user-scoped.
        return object_name.startswith(f"skill-files/{user_id}/")

    if object_name.startswith("workspace/"):
        parts = object_name.split("/")
        return (
            len(parts) >= 5
            and parts[1] == user_id
            and parts[3] == "outputs"
        )

    # Check if file is in user's attachments folder
    # Pattern: attachments/{user_id}/*
    if object_name.startswith(f"attachments/{user_id}/"):
        return True

    # For backward compatibility, allow access to files in root attachments folder
    # Pattern: attachments/{filename} (no user_id subfolder)
    if object_name.startswith("attachments/") and "/" not in object_name.replace("attachments/", "", 1):
        # Old format: attachments/filename (no subdirectory)
        # Allow access for backward compatibility
        return is_read

    return False


def check_file_access_batch(
    object_names: List[str],
    user_id: Optional[str],
    caller_tenant_id: Optional[str] = None,
    required_permission: str = "READ",
) -> Dict[str, bool]:
    """
    Batch check file access permissions.

    Args:
        object_names: List of file object names
        user_id: Current user ID
        caller_tenant_id: Caller's tenant ID for ASSET_OWNER path checks

    Returns:
        Dict mapping object_name to access permission (True/False)
    """
    return {
        obj_name: check_file_access(
            obj_name,
            user_id,
            caller_tenant_id,
            required_permission=required_permission,
        )
        for obj_name in object_names
    }


def validate_s3_url_access(
    object_name: str,
    user_id: Optional[str],
    caller_tenant_id: Optional[str] = None,
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

    if not check_file_access(object_name, user_id, caller_tenant_id):
        logger.warning(
            f"[validate_s3_url_access] Access denied: object_name={object_name}, user_id={user_id}")
        raise PermissionError(
            f"Access denied: You don't have permission to access this file ({object_name})")


def validate_urls_access(
    urls: List[str],
    user_id: Optional[str],
    caller_tenant_id: Optional[str] = None,
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
