"""
User service layer - handles user-related business logic
"""
import logging
from typing import Dict, Any, List

from consts.exceptions import ValidationError
from database.user_tenant_db import (
    get_users_by_tenant_id, update_user_tenant_role, get_user_tenant_by_user_id,
    soft_delete_user_tenant_by_user_id
)
from database.group_db import remove_user_from_all_groups
from database.memory_config_db import soft_delete_all_configs_by_user_id
from database.conversation_db import soft_delete_all_conversations_by_user
from utils.auth_utils import get_supabase_admin_client
from utils.memory_utils import build_memory_config
from nexent.memory.memory_service import clear_memory

logger = logging.getLogger(__name__)


def get_users(tenant_id: str, page: int = 1, page_size: int = 20,
              sort_by: str = "created_at", sort_order: str = "desc") -> Dict[str, Any]:
    """
    Get users belonging to a specific tenant with pagination and sorting

    Args:
        tenant_id (str): Tenant ID
        page (int): Page number (1-based)
        page_size (int): Number of items per page
        sort_by (str): Field to sort by
        sort_order (str): Sort order (asc or desc)

    Returns:
        Dict[str, Any]: Dictionary containing users list and pagination info
    """
    # Get user-tenant relationships from database with pagination and sorting
    result = get_users_by_tenant_id(tenant_id, page, page_size, sort_by, sort_order)

    # For now, return basic user information from the relationships
    # In the future, this could be enhanced to fetch full user details from Supabase
    users = []
    for relationship in result["users"]:
        user_info = {
            "id": relationship["user_id"],
            "username": relationship.get("user_email"),
            "role": relationship["user_role"],
            "tenant_id": relationship["tenant_id"]
        }
        users.append(user_info)

    return {
        "users": users,
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "total_pages": (result["total"] + page_size - 1) // page_size
    }


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
    from database.user_tenant_db import update_user_tenant_role

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


async def delete_user_and_cleanup(user_id: str, tenant_id: str) -> None:
    """
    Permanently delete user account and all related data.

    This performs complete cleanup:
    1) Soft-delete user-tenant relation and remove from all groups
    2) Soft-delete memory user configs and all conversations
    3) Clear user-level memories in memory store
    4) Permanently delete user from Supabase

    Args:
        user_id (str): User ID to delete
        tenant_id (str): Tenant ID for memory operations
    """
    try:
        logger.debug(f"Start permanently deleting user {user_id} and all related data...")

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

        # 4) Clear memory records
        try:
            memory_config = build_memory_config(tenant_id)
            await clear_memory(
                memory_level="user",
                memory_config=memory_config,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            await clear_memory(
                memory_level="user_agent",
                memory_config=memory_config,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            logger.debug("\tUser memories cleared.")
        except Exception as e:
            logger.error(f"Failed clearing memory for user {user_id}: {e}")

        # 5) Delete from Supabase
        try:
            admin_client = get_supabase_admin_client()
            if admin_client and hasattr(admin_client.auth, "admin"):
                admin_client.auth.admin.delete_user(user_id)
                logger.debug("\tSupabase user deleted.")
            else:
                raise RuntimeError("Supabase admin client not available")
        except Exception as e:
            logger.error(f"Failed deleting Supabase user {user_id}: {e}")

        logger.info(f"Permanently deleted user {user_id} and all related data.")

    except Exception as exc:
        logger.error(f"Unexpected error in delete_user_and_cleanup for {user_id}: {str(exc)}")
        raise
