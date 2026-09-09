"""
User service layer - handles user-related business logic
"""
import logging
from typing import Any, Dict, List, Optional

from database.user_tenant_db import (
    get_users_by_tenant_id, update_user_tenant_role, get_user_tenant_by_user_id,
    soft_delete_user_tenant_by_user_id
)
from database.group_db import remove_user_from_all_groups, query_groups_by_users
from database.memory_config_db import soft_delete_all_configs_by_user_id
from database.conversation_db import soft_delete_all_conversations_by_user
from database.knowledge_db import get_private_knowledge_info_by_creator
from database.oauth_account_db import soft_delete_all_oauth_accounts_by_user_id
from consts.const import IS_SPEED_MODE
from consts.exceptions import ForbiddenError, NotFoundException
from utils.auth_utils import get_supabase_admin_client

logger = logging.getLogger(__name__)


def get_users(tenant_id: str, page: Optional[int] = 1, page_size: Optional[int] = 20,
              sort_by: str = "created_at", sort_order: str = "desc",
              search: Optional[str] = None, roles: Optional[List[str]] = None,
              group_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    """
    Get users belonging to a specific tenant with pagination and sorting

    Args:
        tenant_id (str): Tenant ID
        page (Optional[int]): Page number (1-based). If None, returns all data
        page_size (Optional[int]): Number of items per page. If None, returns all data
        sort_by (str): Field to sort by
        sort_order (str): Sort order (asc or desc)

    Returns:
        Dict[str, Any]: Dictionary containing users list and pagination info
    """
    # Get user-tenant relationships from database with pagination and sorting
    if search or roles or group_ids:
        result = get_users_by_tenant_id(
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            search=search,
            roles=roles,
            group_ids=group_ids,
        )
    else:
        result = get_users_by_tenant_id(tenant_id, page, page_size, sort_by, sort_order)

    # Batch fetch group names for all users in a single query
    tenant_user_ids = [r["user_id"] for r in result["users"]]
    user_group_map = query_groups_by_users(tenant_user_ids)

    users = [
        {
            "id": r["user_id"],
            "username": r.get("user_email"),
            "role": r["user_role"],
            "tenant_id": r["tenant_id"],
            "group_names": user_group_map.get(r["user_id"], []),
        }
        for r in result["users"]
    ]

    # Calculate pagination info only if pagination is used
    if page is not None and page_size is not None:
        return {
            "users": users,
            "total": result["total"],
            "page": page,
            "page_size": page_size,
            "total_pages": (result["total"] + page_size - 1) // page_size
        }
    return {
        "users": users,
        "total": result["total"]
    }


def get_users_for_requester(
    tenant_id: str,
    page: Optional[int] = 1,
    page_size: Optional[int] = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    search: Optional[str] = None,
    roles: Optional[List[str]] = None,
    group_ids: Optional[List[int]] = None,
    *,
    requester_tenant_id: str,
    requester_role: str,
) -> Dict[str, Any]:
    """List users after enforcing role and tenant boundaries."""
    role = (requester_role or "").upper()
    is_speed_admin = IS_SPEED_MODE and role == "SPEED"
    if role == "SU" or is_speed_admin:
        pass
    elif role == "ADMIN" and tenant_id == requester_tenant_id:
        pass
    else:
        raise ForbiddenError("Not authorized to list users for this tenant")

    # Keep the legacy call shape when no filters are supplied. Besides avoiding
    # unnecessary arguments, this preserves compatibility with callers that
    # mock the pre-filter signature.
    if search or roles or group_ids:
        return get_users(
            tenant_id, page, page_size, sort_by, sort_order, search, roles, group_ids
        )
    return get_users(tenant_id, page, page_size, sort_by, sort_order)


async def update_user(user_id: str, update_data: Dict[str, Any], updated_by: str) -> Dict[str, Any]:
    """
    Update user information

    Args:
        user_id (str): User ID to update
        update_data (Dict[str, Any]): Update data containing role
        updated_by (str): ID of the user making the update

    Returns:
        Dict[str, Any]: Updated user information

    Raises:
        ValueError: When user not found or invalid data
    """
    try:
        # Validate role if provided
        if "role" in update_data:
            valid_roles = ["ADMIN", "DEV", "USER"]
            if update_data["role"] not in valid_roles:
                raise ValueError(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

        # Update user role in database
        success = update_user_tenant_role(user_id, update_data.get("role"), updated_by)

        if not success:
            raise ValueError(f"User {user_id} not found or update failed")

        # Get updated user information
        user_tenant_data = get_user_tenant_by_user_id(user_id)

        if not user_tenant_data:
            raise ValueError(f"User {user_id} not found after update")

        user_info = {
            "id": user_tenant_data["user_id"],
            "username": user_tenant_data.get("user_email"),
            "role": user_tenant_data["user_role"]
        }

        logger.info(f"Updated user {user_id} role to {update_data.get('role')} by user {updated_by}")
        return user_info

    except Exception as exc:
        logger.error(f"Failed to update user {user_id}: {str(exc)}")
        raise


async def update_user_for_requester(
    user_id: str,
    update_data: Dict[str, Any],
    *,
    updated_by: str,
    requester_tenant_id: str,
    requester_role: str,
) -> Dict[str, Any]:
    """Update a user after enforcing management role and tenant boundaries."""
    target_user = get_user_tenant_by_user_id(user_id)
    if not target_user:
        raise NotFoundException(f"User {user_id} not found")

    role = (requester_role or "").upper()
    target_role = str(target_user.get("user_role") or "").upper()
    target_tenant_id = target_user.get("tenant_id")
    is_speed_admin = IS_SPEED_MODE and role == "SPEED"

    if role == "SU" or is_speed_admin:
        pass
    elif role == "ADMIN" and target_tenant_id == requester_tenant_id and target_role != "SU":
        pass
    else:
        raise ForbiddenError("Not authorized to update this user")

    return await update_user(user_id, update_data, updated_by)


async def _delete_private_knowledge_bases(user_id: str, tenant_id: str) -> Optional[Dict[str, int]]:
    """Delete PRIVATE knowledge bases created by a user."""
    private_kbs = get_private_knowledge_info_by_creator(tenant_id, user_id)
    if not private_kbs:
        return None

    from management.services.knowledge_base.service import (
        ElasticSearchService,
        get_vector_db_core,
    )

    vdb_core = get_vector_db_core()
    succeeded = 0
    failed = 0
    for kb in private_kbs:
        index_name = kb.get("index_name")
        kb_id = kb.get("knowledge_id")
        if not index_name:
            failed += 1
            logger.error(
                "Personal KB %s for user %s has no index_name",
                kb_id,
                user_id,
            )
            continue
        try:
            await ElasticSearchService.full_delete_knowledge_base(
                index_name, vdb_core, user_id
            )
            succeeded += 1
        except Exception:
            failed += 1
            logger.exception(
                "Failed deleting personal KB for user %s kb_id %s index_name %s",
                user_id,
                kb_id,
                index_name,
            )

    cleanup_result = {
        "total": len(private_kbs),
        "succeeded": succeeded,
        "failed": failed,
    }
    logger.info("Personal KB cleanup for user %s: %s", user_id, cleanup_result)
    return cleanup_result


async def delete_user_and_cleanup(user_id: str, tenant_id: str) -> None:
    """
    Permanently delete user account and all related data.

    This performs complete cleanup:
    1) Soft-delete user-tenant relation and remove from all groups
    2) Soft-delete memory user configs and all conversations
    3) Clear user-level memories in memory store
    4) Delete personal KBs created by the user
    5) Permanently delete user from Supabase

    Args:
        user_id (str): User ID to delete
        tenant_id (str): Tenant ID for memory operations
    """
    try:
        logger.debug(f"Start permanently deleting user {user_id} and all related data...")
        user_tenant = get_user_tenant_by_user_id(user_id)
        has_supabase_identity = bool(user_tenant and user_tenant.get("user_email"))

        # 1) Core user deletion (soft-delete user-tenant and groups)
        try:
            tenant_deleted = soft_delete_user_tenant_by_user_id(user_id, user_id)
            if not tenant_deleted:
                raise ValueError(f"User {user_id} not found in any tenant")

            remove_user_from_all_groups(user_id, user_id)
            logger.debug("\tUser tenant relationship and groups deleted.")
        except Exception as e:
            logger.error(f"Failed core deletion for user {user_id}: {e}")

        # 2) Soft-delete memory configs
        try:
            soft_delete_all_configs_by_user_id(user_id, actor=user_id)
            logger.debug("\tMemory user configs deleted.")
        except Exception as e:
            logger.error(f"Failed deleting configs for user {user_id}: {e}")

        # 3) Soft-delete conversations
        try:
            deleted_convs = soft_delete_all_conversations_by_user(user_id)
            logger.debug(f"\t{deleted_convs} conversations deleted.")
        except Exception as e:
            logger.error(f"Failed deleting conversations for user {user_id}: {e}")

        # 4) Memory record cleanup: in the new Memory system this is performed
        # by ``MemoryService.forget_user`` (PG + ES purge). The legacy
        # mem0-era ``clear_memory`` path has been removed; the new path will
        # be wired in once the storage layer lands in Phase 2.
        # 5) Soft-delete OAuth account bindings
        try:
            deleted_oauth = soft_delete_all_oauth_accounts_by_user_id(user_id, user_id)
            logger.debug(f"\t{deleted_oauth} OAuth account bindings deleted.")
        except Exception as e:
            logger.error(f"Failed deleting OAuth accounts for user {user_id}: {e}")

        # 6) Revoke all API keys before the identity is removed.
        try:
            from database.token_db import soft_delete_tokens_by_user

            soft_delete_tokens_by_user(user_id, user_id)
            logger.debug("\tUser API keys revoked.")
        except Exception as e:
            logger.error(f"Failed revoking API keys for user {user_id}: {e}")

        # 7) Delete from Supabase
        if has_supabase_identity:
            try:
                admin_client = get_supabase_admin_client()
                if admin_client and hasattr(admin_client.auth, "admin"):
                    admin_client.auth.admin.delete_user(user_id)
                    logger.debug("\tSupabase user deleted.")
                else:
                    raise RuntimeError("Supabase admin client not available")
            except Exception as e:
                logger.error(f"Failed deleting Supabase user {user_id}: {e}")

        # 7) Delete PRIVATE personal KBs created by the user. Shared KBs
        # created by the user are intentionally left untouched.
        cleanup_result = None
        try:
            cleanup_result = await _delete_private_knowledge_bases(user_id, tenant_id)
        except Exception:
            logger.exception("Failed personal KB cleanup for user %s", user_id)

        logger.info(f"Permanently deleted user {user_id} and all related data.")
        return cleanup_result

    except Exception as exc:
        logger.error(f"Unexpected error in delete_user_and_cleanup for {user_id}: {str(exc)}")
        raise
