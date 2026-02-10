"""
Group service for managing groups and group memberships.
"""
import logging
from typing import Any, Dict, List, Optional, Union

from database.group_db import (
    query_groups,
    query_groups_by_tenant,
    add_group,
    modify_group,
    remove_group,
    add_user_to_group,
    remove_user_from_group,
    query_group_users,
    query_groups_by_user,
    query_group_ids_by_user,
    check_user_in_group,
    count_group_users,
    check_group_name_exists
)
from database.user_tenant_db import get_user_tenant_by_user_id
from database.tenant_config_db import get_single_config_info, insert_config, update_config_by_tenant_config_id
from consts.exceptions import NotFoundException, UnauthorizedError, ValidationError
from consts.const import DEFAULT_GROUP_ID
from services.tenant_service import get_tenant_info

logger = logging.getLogger(__name__)


def get_group_info(group_id: Union[int, str, List[int]]) -> Union[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Get group(s) by group ID(s).

    Args:
        group_id: Group ID(s) - can be int, comma-separated string, or list of ints

    Returns:
        Single group dict with group_id, group_name, group_description if int provided,
        list of group dicts if string/list provided

    Raises:
        NotFoundException: When group not found
    """
    result = query_groups(group_id)

    if isinstance(group_id, int) and result is None:
        raise NotFoundException(f"Group {group_id} not found")

    # Extract only the required fields: group_id, group_name, group_description
    if isinstance(group_id, int) and result is not None:
        # Single group result
        return {
            "group_id": result.get("group_id"),
            "group_name": result.get("group_name"),
            "group_description": result.get("group_description")
        }
    elif isinstance(group_id, (str, list)) and result is not None:
        # List of groups result
        filtered_groups = []
        for group in result:
            filtered_groups.append({
                "group_id": group.get("group_id"),
                "group_name": group.get("group_name"),
                "group_description": group.get("group_description")
            })
        return filtered_groups

    return result


def get_groups_by_tenant(tenant_id: str, page: int = 1, page_size: int = 20,
                         sort_by: str = "created_at", sort_order: str = "desc") -> Dict[str, Any]:
    """
    Get groups for a specific tenant with pagination and sorting.

    Args:
        tenant_id (str): Tenant ID
        page (int): Page number (1-based)
        page_size (int): Number of items per page
        sort_by (str): Field to sort by
        sort_order (str): Sort order (asc or desc)

    Returns:
        Dict[str, Any]: Dictionary containing groups list and total count
    """
    # Get paginated results and total count
    result = query_groups_by_tenant(tenant_id, page, page_size, sort_by, sort_order)

    # Filter to only return required fields for each group and add user count
    filtered_groups = []
    for group in result["groups"]:
        group_id = group.get("group_id")
        user_count = count_group_users(group_id) if group_id else 0
        filtered_groups.append({
            "group_id": group.get("group_id"),
            "group_name": group.get("group_name"),
            "group_description": group.get("group_description"),
            "user_count": user_count
        })

    return {
        "groups": filtered_groups,
        "total": result["total"]
    }


def get_tenant_default_group_id(tenant_id: str) -> Optional[int]:
    """
    Get the default group ID for a tenant.

    Args:
        tenant_id (str): Tenant ID

    Returns:
        Optional[int]: Default group ID if exists, None otherwise
    """
    try:
        tenant_info = get_tenant_info(tenant_id)
        default_group_id = tenant_info.get("default_group_id")
        return int(default_group_id) if default_group_id else None
    except Exception as e:
        logger.warning(f"Failed to get default group ID for tenant {tenant_id}: {str(e)}")
        return None


def set_tenant_default_group_id(tenant_id: str, group_id: int, updated_by: Optional[str] = None) -> bool:
    """
    Set the default group ID for a tenant.

    Args:
        tenant_id (str): Tenant ID
        group_id (int): Group ID to set as default
        updated_by (Optional[str]): User ID performing the update

    Returns:
        bool: Whether the operation was successful

    Raises:
        NotFoundException: When tenant or group not found
        ValidationError: When group doesn't belong to the tenant
    """
    # Verify tenant exists
    try:
        tenant_info = get_tenant_info(tenant_id)
        if not tenant_info:
            raise NotFoundException(f"Tenant {tenant_id} not found")
    except NotFoundException:
        raise

    # Verify group exists and belongs to the tenant
    group = query_groups(group_id)
    if not group:
        raise NotFoundException(f"Group {group_id} not found")

    # Check if group belongs to the tenant (groups are tenant-specific)
    if str(group.get("tenant_id")) != tenant_id:
        raise ValidationError(
            f"Group {group_id} does not belong to tenant {tenant_id}")

    try:
        # Try to update existing default group config
        existing_config = get_single_config_info(tenant_id, DEFAULT_GROUP_ID)
        if existing_config:
            success = update_config_by_tenant_config_id(
                existing_config["tenant_config_id"],
                str(group_id)
            )
            if success:
                logger.info(
                    f"Updated default group ID to {group_id} for tenant {tenant_id} by user {updated_by}")
        else:
            # Create new default group config
            config_data = {
                "tenant_id": tenant_id,
                "config_key": DEFAULT_GROUP_ID,
                "config_value": str(group_id),
                "created_by": updated_by,
                "updated_by": updated_by
            }
            success = insert_config(config_data)
            if success:
                logger.info(
                    f"Set default group ID to {group_id} for tenant {tenant_id} by user {updated_by}")

        return success

    except Exception as e:
        logger.error(
            f"Failed to set default group ID to {group_id} for tenant {tenant_id}: {str(e)}")
        raise ValidationError(f"Failed to set default group: {str(e)}")


def create_group(tenant_id: str, group_name: str, group_description: Optional[str] = None,
               user_id: str = None) -> Dict[str, Any]:
    """
    Create a new group.

    Args:
        tenant_id (str): Tenant ID
        group_name (str): Group name
        group_description (Optional[str]): Group description
        user_id (str): Current user ID

    Returns:
        Dict[str, Any]: Created group information

    Raises:
        NotFoundException: When user not found
        UnauthorizedError: When user doesn't have permission
        ValidationError: When group name already exists in the tenant
    """
    # Check user permission
    if user_id:
        user_info = get_user_tenant_by_user_id(user_id)
        if not user_info:
            raise NotFoundException(f"User {user_id} not found")

        user_role = user_info.get("user_role", "USER")
        if user_role not in ["SU", "ADMIN"]:
            raise UnauthorizedError(f"User role {user_role} not authorized to create groups")

    # Check if group name already exists in the tenant
    if check_group_name_exists(tenant_id, group_name):
        raise ValidationError(f"Group name '{group_name}' already exists in this tenant")

    # Create group
    group_id = add_group(
        tenant_id=tenant_id,
        group_name=group_name,
        group_description=group_description,
        created_by=user_id
    )

    logger.info(f"Created group {group_name} for tenant {tenant_id} by user {user_id}")

    return {
        "group_id": group_id,
        "group_name": group_name,
        "group_description": group_description
    }


def update_group(group_id: int, updates: Dict[str, Any], user_id: str) -> bool:
    """
    Update group information.

    Args:
        group_id (int): Group ID
        updates (Dict[str, Any]): Fields to update
        user_id (str): Current user ID

    Returns:
        bool: Whether update was successful

    Raises:
        NotFoundException: When user or group not found
        UnauthorizedError: When user doesn't have permission
        ValidationError: When group name already exists in the tenant
    """
    # Check user permission
    user_info = get_user_tenant_by_user_id(user_id)
    if not user_info:
        raise NotFoundException(f"User {user_id} not found")

    user_role = user_info.get("user_role", "USER")
    if user_role not in ["SU", "ADMIN"]:
        raise UnauthorizedError(f"User role {user_role} not authorized to update groups")

    # Check if group exists
    group = query_groups(group_id)
    if not group:
        raise NotFoundException(f"Group {group_id} not found")

    tenant_id = group.get("tenant_id")

    # Check if new group name already exists in the tenant (when updating group_name)
    if "group_name" in updates and updates["group_name"]:
        if check_group_name_exists(tenant_id, updates["group_name"], exclude_group_id=group_id):
            raise ValidationError(f"Group name '{updates['group_name']}' already exists in this tenant")

    # Update group
    success = modify_group(
        group_id=group_id,
        updates=updates,
        updated_by=user_id
    )

    if success:
        logger.info(f"Updated group {group_id} by user {user_id}")

    return success


def delete_group(group_id: int, user_id: str) -> bool:
    """
    Delete group.

    Args:
        group_id (int): Group ID
        user_id (str): Current user ID

    Returns:
        bool: Whether deletion was successful

    Raises:
        NotFoundException: When user or group not found
        UnauthorizedError: When user doesn't have permission
    """
    # Check user permission
    user_info = get_user_tenant_by_user_id(user_id)
    if not user_info:
        raise NotFoundException(f"User {user_id} not found")

    user_role = user_info.get("user_role", "USER")
    if user_role not in ["SU", "ADMIN"]:
        raise UnauthorizedError(f"User role {user_role} not authorized to delete groups")

    # Check if group exists
    group = query_groups(group_id)
    if not group:
        raise NotFoundException(f"Group {group_id} not found")

    # Delete group
    success = remove_group(
        group_id=group_id,
        updated_by=user_id
    )

    if success:
        logger.info(f"Deleted group {group_id} by user {user_id}")

    return success


def add_user_to_single_group(group_id: int, user_id: str, current_user_id: str) -> Dict[str, Any]:
    """
    Add user to group.

    Args:
        group_id (int): Group ID
        user_id (str): User ID to add
        current_user_id (str): Current user ID performing the action

    Returns:
        Dict[str, Any]: Group membership information

    Raises:
        NotFoundException: When user or group not found
        UnauthorizedError: When user doesn't have permission
    """
    # Check current user permission
    user_info = get_user_tenant_by_user_id(current_user_id)
    if not user_info:
        raise UnauthorizedError(f"User {current_user_id} not found")

    # Check if group exists
    group = query_groups(group_id)
    if not group:
        raise NotFoundException(f"Group {group_id} not found")

    # Check if user is already in group
    if check_user_in_group(user_id, group_id):
        return {
            "group_id": group_id,
            "user_id": user_id,
            "already_member": True
        }

    # Add user to group
    group_user_id = add_user_to_group(
        group_id=group_id,
        user_id=user_id,
        created_by=current_user_id
    )

    logger.info(f"Added user {user_id} to group {group_id} by user {current_user_id}")

    return {
        "group_user_id": group_user_id,
        "group_id": group_id,
        "user_id": user_id,
        "already_member": False
    }


def remove_user_from_single_group(group_id: int, user_id: str, current_user_id: str) -> bool:
    """
    Remove user from group.

    Args:
        group_id (int): Group ID
        user_id (str): User ID to remove
        current_user_id (str): Current user ID performing the action

    Returns:
        bool: Whether removal was successful

    Raises:
        NotFoundException: When user or group not found
        UnauthorizedError: When user doesn't have permission
    """
    # Check current user permission
    user_info = get_user_tenant_by_user_id(current_user_id)
    if not user_info:
        raise UnauthorizedError(f"User {current_user_id} not found")

    user_role = user_info.get("user_role", "USER")
    if user_role not in ["SU", "ADMIN"]:
        raise UnauthorizedError(f"User role {user_role} not authorized to manage group memberships")

    # Check if group exists
    group = query_groups(group_id)
    if not group:
        raise NotFoundException(f"Group {group_id} not found")

    # Remove user from group
    success = remove_user_from_group(
        group_id=group_id,
        user_id=user_id,
        updated_by=current_user_id
    )

    if success:
        logger.info(f"Removed user {user_id} from group {group_id} by user {current_user_id}")

    return success


def get_group_users(group_id: int) -> List[Dict[str, Any]]:
    """
    Get all users in a group with their details.

    Args:
        group_id (int): Group ID

    Returns:
        List[Dict[str, Any]]: List of group user records with user details

    Raises:
        NotFoundException: When group not found
    """
    # Check if group exists
    group = query_groups(group_id)
    if not group:
        raise NotFoundException(f"Group {group_id} not found")

    # Get group membership records
    group_memberships = query_group_users(group_id)

    filtered_users = []
    for membership in group_memberships:
        user_id = membership.get("user_id")
        if user_id:
            # Get user details from user_tenant table
            user_info = get_user_tenant_by_user_id(user_id)
            if user_info:
                filtered_users.append({
                    "id": user_id,  # Keep user_id as string
                    "username": user_info.get("user_email", ""),
                    "role": user_info.get("user_role", "")
                })

    return filtered_users


def get_group_user_count(group_id: int) -> int:
    """
    Get user count in a group.

    Args:
        group_id (int): Group ID

    Returns:
        int: Number of users in the group

    Raises:
        NotFoundException: When group not found
    """
    # Check if group exists
    group = query_groups(group_id)
    if not group:
        raise NotFoundException(f"Group {group_id} not found")

    return count_group_users(group_id)


def add_user_to_groups(user_id: str, group_ids: List[int], current_user_id: str) -> List[Dict[str, Any]]:
    """
    Add user to multiple groups.

    Args:
        user_id (str): User ID to add
        group_ids (List[int]): List of group IDs
        current_user_id (str): Current user ID performing the action

    Returns:
        List[Dict[str, Any]]: List of group membership results

    Raises:
        UnauthorizedError: When user doesn't have permission
    """
    results = []
    for group_id in group_ids:
        try:
            result = add_user_to_single_group(
                group_id, user_id, current_user_id)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to add user {user_id} to group {group_id}: {str(e)}")
            results.append({
                "group_id": group_id,
                "user_id": user_id,
                "error": str(e)
            })

    return results


def update_group_members(group_id: int, user_ids: List[str], current_user_id: str) -> Dict[str, Any]:
    """
    Update group members by setting the exact list of users that should be in the group.

    Args:
        group_id (int): Group ID
        user_ids (List[str]): List of user IDs that should be in the group
        current_user_id (str): Current user ID performing the action

    Returns:
        Dict[str, Any]: Update results with added/removed counts

    Raises:
        NotFoundException: When group not found
        UnauthorizedError: When user doesn't have permission
    """
    # Check current user permission
    user_info = get_user_tenant_by_user_id(current_user_id)
    if not user_info:
        raise UnauthorizedError(f"User {current_user_id} not found")

    # Check if group exists
    group = query_groups(group_id)
    if not group:
        raise NotFoundException(f"Group {group_id} not found")

    # Get current group members
    current_members = get_group_users(group_id)
    current_user_ids = {str(member["id"]) for member in current_members}

    # Convert target user_ids to set for comparison
    target_user_ids = set(user_ids)

    # Find users to add and remove
    users_to_add = target_user_ids - current_user_ids
    users_to_remove = current_user_ids - target_user_ids

    added_count = 0
    removed_count = 0

    # Add new members
    for user_id in users_to_add:
        try:
            add_user_to_single_group(group_id, user_id, current_user_id)
            added_count += 1
        except Exception as e:
            logger.error(f"Failed to add user {user_id} to group {group_id}: {str(e)}")

    # Remove old members
    for user_id in users_to_remove:
        try:
            remove_user_from_single_group(group_id, user_id, current_user_id)
            removed_count += 1
        except Exception as e:
            logger.error(f"Failed to remove user {user_id} from group {group_id}: {str(e)}")

    logger.info(f"Updated group {group_id} members: added {added_count}, removed {removed_count} by user {current_user_id}")

    return {
        "group_id": group_id,
        "added_count": added_count,
        "removed_count": removed_count,
        "total_members": len(target_user_ids)
    }
