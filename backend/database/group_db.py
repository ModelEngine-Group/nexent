"""
Database operations for group management
"""
from typing import Any, Dict, List, Optional, Union

from database.client import as_dict, get_db_session
from database.db_models import TenantGroupInfo, TenantGroupUser
from utils.str_utils import convert_string_to_list


def query_groups(group_id: Union[int, str, List[int]]) -> Union[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Query group(s) by group ID(s)

    Args:
        group_id: Group ID(s) - can be int, comma-separated string, or list of ints

    Returns:
        Single group dict if int provided, list of group dicts if string/list provided
    """
    # Convert input to list of integers
    if isinstance(group_id, int):
        group_ids = [group_id]
        return_single = True
    elif isinstance(group_id, str):
        group_ids = convert_string_to_list(group_id)
        return_single = False
    elif isinstance(group_id, list):
        group_ids = group_id
        return_single = False
    else:
        raise ValueError("group_id must be int, str, or List[int]")

    if not group_ids:
        return [] if not return_single else None

    with get_db_session() as session:
        result = session.query(TenantGroupInfo).filter(
            TenantGroupInfo.group_id.in_(group_ids),
            TenantGroupInfo.delete_flag == "N"
        ).all()

        groups = [as_dict(record) for record in result]

        # Return single result if single ID was provided
        if return_single:
            return groups[0] if groups else None
        else:
            return groups


def query_groups_by_tenant(tenant_id: str, page: int = 1, page_size: int = 20,
                           sort_by: str = "created_at", sort_order: str = "desc") -> Dict[str, Any]:
    """
    Query groups for a tenant with pagination and sorting

    Args:
        tenant_id (str): Tenant ID
        page (int): Page number (1-based)
        page_size (int): Number of items per page
        sort_by (str): Field to sort by
        sort_order (str): Sort order (asc or desc)

    Returns:
        Dict[str, Any]: Dictionary containing groups list and total count
    """
    offset = (page - 1) * page_size

    with get_db_session() as session:
        # Get total count
        total = session.query(TenantGroupInfo).filter(
            TenantGroupInfo.tenant_id == tenant_id,
            TenantGroupInfo.delete_flag == "N"
        ).count()

        # Build base query
        query = session.query(TenantGroupInfo).filter(
            TenantGroupInfo.tenant_id == tenant_id,
            TenantGroupInfo.delete_flag == "N"
        )

        # Add sorting
        if sort_by == "created_at":
            if sort_order == "desc":
                query = query.order_by(TenantGroupInfo.create_time.desc())
            else:
                query = query.order_by(TenantGroupInfo.create_time.asc())

        # Get paginated results
        result = query.offset(offset).limit(page_size).all()

        return {
            "groups": [as_dict(record) for record in result],
            "total": total
        }


def add_group(tenant_id: str, group_name: str, group_description: Optional[str] = None,
              created_by: Optional[str] = None) -> int:
    """
    Add a new group

    Args:
        tenant_id (str): Tenant ID
        group_name (str): Group name
        group_description (Optional[str]): Group description
        created_by (Optional[str]): Created by user

    Returns:
        int: Created group ID
    """
    with get_db_session() as session:
        group = TenantGroupInfo(
            tenant_id=tenant_id,
            group_name=group_name,
            group_description=group_description,
            created_by=created_by,
            updated_by=created_by
        )
        session.add(group)
        session.flush()  # To get the ID
        return group.group_id


def modify_group(group_id: int, updates: Dict[str, Any], updated_by: Optional[str] = None) -> bool:
    """
    Modify group information

    Args:
        group_id (int): Group ID
        updates (Dict[str, Any]): Fields to update
        updated_by (Optional[str]): Updated by user

    Returns:
        bool: Whether update was successful
    """
    with get_db_session() as session:
        update_data = updates.copy()
        if updated_by:
            update_data["updated_by"] = updated_by

        result = session.query(TenantGroupInfo).filter(
            TenantGroupInfo.group_id == group_id,
            TenantGroupInfo.delete_flag == "N"
        ).update(update_data, synchronize_session=False)

        return result > 0


def remove_group(group_id: int, updated_by: Optional[str] = None) -> bool:
    """
    Remove group (soft delete) and all its user relationships

    Args:
        group_id (int): Group ID
        updated_by (Optional[str]): Updated by user

    Returns:
        bool: Whether removal was successful
    """
    with get_db_session() as session:
        update_data: Dict[str, Any] = {"delete_flag": "Y"}
        if updated_by:
            update_data["updated_by"] = updated_by

        # Soft delete the group
        result = session.query(TenantGroupInfo).filter(
            TenantGroupInfo.group_id == group_id,
            TenantGroupInfo.delete_flag == "N"
        ).update(update_data, synchronize_session=False)

        # Soft delete all user-group relationships for this group
        session.query(TenantGroupUser).filter(
            TenantGroupUser.group_id == group_id,
            TenantGroupUser.delete_flag == "N"
        ).update(update_data, synchronize_session=False)

        return result > 0


def add_user_to_group(group_id: int, user_id: str, created_by: Optional[str] = None) -> int:
    """
    Add user to group

    Args:
        group_id (int): Group ID
        user_id (str): User ID
        created_by (Optional[str]): Created by user

    Returns:
        int: Created group user ID
    """
    with get_db_session() as session:
        group_user = TenantGroupUser(
            group_id=group_id,
            user_id=user_id,
            created_by=created_by,
            updated_by=created_by
        )
        session.add(group_user)
        session.flush()  # To get the ID
        return group_user.group_user_id


def remove_user_from_group(group_id: int, user_id: str, updated_by: Optional[str] = None) -> bool:
    """
    Remove user from group

    Args:
        group_id (int): Group ID
        user_id (str): User ID
        updated_by (Optional[str]): Updated by user

    Returns:
        bool: Whether removal was successful
    """
    with get_db_session() as session:
        update_data: Dict[str, Any] = {"delete_flag": "Y"}
        if updated_by:
            update_data["updated_by"] = updated_by

        result = session.query(TenantGroupUser).filter(
            TenantGroupUser.group_id == group_id,
            TenantGroupUser.user_id == user_id,
            TenantGroupUser.delete_flag == "N"
        ).update(update_data, synchronize_session=False)

        return result > 0


def query_group_users(group_id: int) -> List[Dict[str, Any]]:
    """
    Query all users in a group

    Args:
        group_id (int): Group ID

    Returns:
        List[Dict[str, Any]]: List of group user records
    """
    with get_db_session() as session:
        result = session.query(TenantGroupUser).filter(
            TenantGroupUser.group_id == group_id,
            TenantGroupUser.delete_flag == "N"
        ).all()

        return [as_dict(record) for record in result]


def query_group_ids_by_user(user_id: str) -> List[int]:
    """
    Query all group IDs for a user

    Args:
        user_id (str): User ID

    Returns:
        List[int]: List of group IDs
    """
    with get_db_session() as session:
        result = session.query(TenantGroupUser.group_id).filter(
            TenantGroupUser.user_id == user_id,
            TenantGroupUser.delete_flag == "N"
        ).all()

        return [record[0] for record in result]


def query_groups_by_user(user_id: str) -> List[Dict[str, Any]]:
    """
    Query all groups for a user

    Args:
        user_id (str): User ID

    Returns:
        List[Dict[str, Any]]: List of group records
    """
    with get_db_session() as session:
        result = session.query(TenantGroupInfo).join(
            TenantGroupUser,
            TenantGroupInfo.group_id == TenantGroupUser.group_id
        ).filter(
            TenantGroupUser.user_id == user_id,
            TenantGroupUser.delete_flag == "N",
            TenantGroupInfo.delete_flag == "N"
        ).all()

        return [as_dict(record) for record in result]


def check_user_in_group(user_id: str, group_id: int) -> bool:
    """
    Check if user is in a specific group

    Args:
        user_id (str): User ID
        group_id (int): Group ID

    Returns:
        bool: Whether user is in the group
    """
    with get_db_session() as session:
        result = session.query(TenantGroupUser).filter(
            TenantGroupUser.group_id == group_id,
            TenantGroupUser.user_id == user_id,
            TenantGroupUser.delete_flag == "N"
        ).first()

        return result is not None


def count_group_users(group_id: int) -> int:
    """
    Count users in a group

    Args:
        group_id (int): Group ID

    Returns:
        int: Number of users in the group
    """
    with get_db_session() as session:
        result = session.query(TenantGroupUser).filter(
            TenantGroupUser.group_id == group_id,
            TenantGroupUser.delete_flag == "N"
        ).count()

        return result


def remove_group_users(group_id: int, removed_by: Optional[str] = None) -> int:
    """
    Remove all users from a group (soft delete all group-user relationships)

    Args:
        group_id (int): Group ID
        removed_by (Optional[str]): User who performed the removal

    Returns:
        int: Number of group memberships removed
    """
    with get_db_session() as session:
        update_data: Dict[str, Any] = {"delete_flag": "Y"}
        if removed_by:
            update_data["updated_by"] = removed_by

        result = session.query(TenantGroupUser).filter(
            TenantGroupUser.group_id == group_id,
            TenantGroupUser.delete_flag == "N"
        ).update(update_data, synchronize_session=False)

        return result


def remove_user_from_all_groups(user_id: str, removed_by: str) -> int:
    """
    Remove user from all groups (soft delete)

    Args:
        user_id (str): User ID to remove
        removed_by (str): User who performed the removal

    Returns:
        int: Number of group memberships removed
    """
    with get_db_session() as session:
        result = session.query(TenantGroupUser).filter(
            TenantGroupUser.user_id == user_id,
            TenantGroupUser.delete_flag == "N"
        ).update({
            "delete_flag": "Y",
            "updated_by": removed_by,
            "update_time": "NOW()"  # This will be handled by the database trigger
        })

        return result


def check_group_name_exists(tenant_id: str, group_name: str, exclude_group_id: Optional[int] = None) -> bool:
    """
    Check if a group with the given name already exists in the tenant

    Args:
        tenant_id (str): Tenant ID
        group_name (str): Group name to check
        exclude_group_id (Optional[int]): Group ID to exclude (for update operations)

    Returns:
        bool: True if group name exists, False otherwise
    """
    with get_db_session() as session:
        query = session.query(TenantGroupInfo).filter(
            TenantGroupInfo.tenant_id == tenant_id,
            TenantGroupInfo.group_name == group_name,
            TenantGroupInfo.delete_flag == "N"
        )

        # Exclude specific group ID for update operations
        if exclude_group_id is not None:
            query = query.filter(TenantGroupInfo.group_id != exclude_group_id)

        result = query.first()
        return result is not None