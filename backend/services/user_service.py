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
from services.tenant_service import get_tenant_info
from utils.auth_utils import get_supabase_admin_client

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


async def delete_user(user_id: str, deleted_by: str) -> bool:
    """
    Soft delete user and remove from all groups

    Args:
        user_id (str): User ID to delete
        deleted_by (str): ID of the user performing the deletion

    Returns:
        bool: True if deletion successful

    Raises:
        ValueError: When user not found
    """
    try:
        # Soft delete user-tenant relationship
        tenant_deleted = soft_delete_user_tenant_by_user_id(user_id, deleted_by)

        if not tenant_deleted:
            raise ValueError(f"User {user_id} not found in any tenant")

        # Remove user from all groups
        try:
            remove_user_from_all_groups(user_id, deleted_by)
        except Exception as group_exc:
            # Log the error but don't fail the entire deletion
            logger.warning(f"Failed to remove user {user_id} from groups: {str(group_exc)}")

        logger.info(f"Soft deleted user {user_id} by user {deleted_by}")
        return True

    except Exception as exc:
        logger.error(f"Failed to delete user {user_id}: {str(exc)}")
        raise
