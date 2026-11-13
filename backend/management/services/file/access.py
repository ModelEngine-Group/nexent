# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from contracts.constants.constants import ASSET_OWNER_ATTACHMENTS_PREFIX
from typing import Dict
from typing import List
from typing import Optional
from infrastructure.object_storage.read_access import (
    can_read_object,
    validate_s3_url_access as validate_s3_url_access,
    validate_urls_access as validate_urls_access,
)

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

    if is_read:
        return can_read_object(object_name, user_id, caller_tenant_id)

    if object_name.startswith(ASSET_OWNER_ATTACHMENTS_PREFIX):
        from management.services.knowledge_base.storage import resolve_storage_object_access

        return resolve_storage_object_access(
            object_name=object_name,
            user_id=user_id,
            tenant_id=caller_tenant_id,
            required_permission=normalized_permission,
        )

    if object_name.startswith("knowledge_base/"):
        from management.services.knowledge_base.storage import resolve_storage_object_access

        return resolve_storage_object_access(
            object_name=object_name,
            user_id=user_id,
            tenant_id=caller_tenant_id,
            required_permission=normalized_permission,
        )

    if object_name.startswith("images_in_attachments/"):
        return False

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
