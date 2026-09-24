"""Knowledge-base permission resolution and reusable permission requirements."""

import logging
from typing import List, Optional

from consts.const import ASSET_OWNER_TENANT_ID, IS_SPEED_MODE, PERMISSION_EDIT
from database.knowledge_db import get_knowledge_record
from database.group_db import query_group_ids_by_user
from database.user_tenant_db import get_user_tenant_by_user_id
from permissions.dac import ResourceAccessControl
from permissions.models import Resource

logger = logging.getLogger("knowledge_base_permission_service")

CREATOR_PERMISSION = "CREATOR"


def resolve_knowledge_base_permission(
    index_name: str,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> Optional[str]:
    """Resolve the current user's permission for one knowledge base."""
    record = get_knowledge_record({"index_name": index_name})
    if not record:
        raise ValueError(f"Knowledge base '{index_name}' not found")

    user_tenant = get_user_tenant_by_user_id(user_id)
    if not user_tenant and not IS_SPEED_MODE:
        return None

    user_role = (user_tenant or {}).get("user_role")
    user_tenant_id = str((user_tenant or {}).get("tenant_id") or tenant_id or "")
    effective_user_role = user_role
    if user_id == user_tenant_id:
        effective_user_role = "ADMIN"
        logger.info("User %s identified as legacy admin", user_id)
    elif IS_SPEED_MODE and not user_role:
        effective_user_role = "SPEED"
    role = (effective_user_role or "").upper()
    if IS_SPEED_MODE and not user_tenant_id:
        user_tenant_id = str(record.get("tenant_id") or tenant_id or "")

    access = ResourceAccessControl.check(
        Resource(
            resource_type="knowledge_base",
            resource_id=index_name,
            tenant_id=record.get("tenant_id"),
            created_by=record.get("created_by"),
            ingroup_permission=record.get("ingroup_permission"),
            group_ids=record.get("group_ids"),
            knowledge_sources=record.get("knowledge_sources"),
        ),
        user_id=user_id,
        role=role,
        user_groups=query_group_ids_by_user(user_id),
        user_tenant_id=user_tenant_id,
        asset_owner_tenant_id=ASSET_OWNER_TENANT_ID,
    )
    return access.permission_label


def require_knowledge_base_permission(
    index_name: str,
    user_id: str,
    tenant_id: Optional[str],
    *,
    accepted_permissions: Optional[set[str]],
    error_message: str,
) -> str:
    """Resolve one permission and enforce the accepted permission set."""
    permission = resolve_knowledge_base_permission(index_name, user_id, tenant_id)
    if permission is None or (
        accepted_permissions is not None and permission not in accepted_permissions
    ):
        raise PermissionError(error_message)
    return permission


def require_knowledge_base_edit_permission(
    index_name: str,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> str:
    return require_knowledge_base_permission(
        index_name,
        user_id,
        tenant_id,
        accepted_permissions={PERMISSION_EDIT, CREATOR_PERMISSION},
        error_message="No permission to modify this knowledge base",
    )


def require_knowledge_base_read_permission(
    index_name: str,
    user_id: str,
    tenant_id: Optional[str] = None,
) -> str:
    return require_knowledge_base_permission(
        index_name,
        user_id,
        tenant_id,
        accepted_permissions=None,
        error_message="No permission to access this knowledge base",
    )


def filter_accessible_indices(
    index_names: List[str],
    user_id: str,
    tenant_id: Optional[str] = None,
) -> List[str]:
    """Return the input-order subset for which the user has read access."""
    accessible = []
    for index_name in index_names:
        try:
            permission = resolve_knowledge_base_permission(index_name, user_id, tenant_id)
        except ValueError:
            logger.warning(
                "Knowledge base '%s' not found during permission check, skipping",
                index_name,
            )
            continue
        except Exception as exc:
            logger.warning(
                "Permission check failed for knowledge base '%s': %s",
                index_name,
                exc,
            )
            continue
        if permission is not None:
            accessible.append(index_name)
    return accessible
