"""
Database operations for group management
"""
from typing import Any, Dict, List, Optional

from database.client import as_dict, get_db_session
from database.db_models import TenantGroupInfo, TenantGroupUser


def get_group_by_id(group_id: int) -> Optional[Dict[str, Any]]:
    """
    Get group by group ID

    Args:
        group_id (int): Group ID

    Returns:
        Optional[Dict[str, Any]]: Group record
    """
    with get_db_session() as session:
        result = session.query(TenantGroupInfo).filter(
            TenantGroupInfo.group_id == group_id,
            TenantGroupInfo.delete_flag == "N"
        ).first()

        if result:
            return as_dict(result)
        return None


def get_groups_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Get all groups for a tenant

    Args:
        tenant_id (str): Tenant ID

    Returns:
        List[Dict[str, Any]]: List of group records
    """
    with get_db_session() as session:
        result = session.query(TenantGroupInfo).filter(
            TenantGroupInfo.tenant_id == tenant_id,
            TenantGroupInfo.delete_flag == "N"
        ).all()

        return [as_dict(record) for record in result]


def create_group(tenant_id: str, group_name: str, group_description: Optional[str] = None,
                created_by: Optional[str] = None) -> int:
    """
    Create a new group

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


def update_group(group_id: int, updates: Dict[str, Any], updated_by: Optional[str] = None) -> bool:
    """
    Update group information

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


def soft_delete_group(group_id: int, updated_by: Optional[str] = None) -> bool:
    """
    Soft delete group

    Args:
        group_id (int): Group ID
        updated_by (Optional[str]): Updated by user

    Returns:
        bool: Whether deletion was successful
    """
    with get_db_session() as session:
        update_data: Dict[str, Any] = {"delete_flag": "Y"}
        if updated_by:
            update_data["updated_by"] = updated_by

        result = session.query(TenantGroupInfo).filter(
            TenantGroupInfo.group_id == group_id,
            TenantGroupInfo.delete_flag == "N"
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


def get_group_users(group_id: int) -> List[Dict[str, Any]]:
    """
    Get all users in a group

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


def get_user_groups(user_id: str, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get all groups for a user

    Args:
        user_id (str): User ID
        tenant_id (Optional[str]): Tenant ID filter

    Returns:
        List[Dict[str, Any]]: List of group records
    """
    with get_db_session() as session:
        query = session.query(TenantGroupInfo).join(
            TenantGroupUser,
            TenantGroupInfo.group_id == TenantGroupUser.group_id
        ).filter(
            TenantGroupUser.user_id == user_id,
            TenantGroupUser.delete_flag == "N",
            TenantGroupInfo.delete_flag == "N"
        )

        if tenant_id:
            query = query.filter(TenantGroupInfo.tenant_id == tenant_id)

        result = query.all()
        return [as_dict(record) for record in result]


def is_user_in_group(user_id: str, group_id: int) -> bool:
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


def get_group_user_count(group_id: int) -> int:
    """
    Get user count in a group

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
