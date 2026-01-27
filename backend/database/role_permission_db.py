"""
Database operations for role permission management
"""
from typing import Any, Dict, List, Optional

from database.client import as_dict, get_db_session
from database.db_models import RolePermission


def get_role_permissions(user_role: str) -> List[Dict[str, Any]]:
    """
    Get all permissions for a user role

    Args:
        user_role (str): User role (SU, ADMIN, DEV, USER)

    Returns:
        List[Dict[str, Any]]: List of role permission records
    """
    with get_db_session() as session:
        result = session.query(RolePermission).filter(
            RolePermission.user_role == user_role,
            RolePermission.delete_flag == "N"
        ).all()

        return [as_dict(record) for record in result]


def get_all_role_permissions() -> List[Dict[str, Any]]:
    """
    Get all role permissions

    Returns:
        List[Dict[str, Any]]: List of all role permission records
    """
    with get_db_session() as session:
        result = session.query(RolePermission).filter(
            RolePermission.delete_flag == "N"
        ).all()

        return [as_dict(record) for record in result]


def create_role_permission(user_role: str, permission_category: Optional[str] = None,
                          permission_type: Optional[str] = None, permission_subtype: Optional[str] = None,
                          created_by: Optional[str] = None) -> int:
    """
    Create a new role permission

    Args:
        user_role (str): User role
        permission_category (Optional[str]): Permission category
        permission_type (Optional[str]): Permission type
        permission_subtype (Optional[str]): Permission subtype
        created_by (Optional[str]): Created by user

    Returns:
        int: Created role permission ID
    """
    with get_db_session() as session:
        permission = RolePermission(
            user_role=user_role,
            permission_category=permission_category,
            permission_type=permission_type,
            permission_subtype=permission_subtype,
            created_by=created_by,
            updated_by=created_by
        )
        session.add(permission)
        session.flush()  # To get the ID
        return permission.role_permission_id


def update_role_permission(role_permission_id: int, updates: Dict[str, Any],
                          updated_by: Optional[str] = None) -> bool:
    """
    Update role permission

    Args:
        role_permission_id (int): Role permission ID
        updates (Dict[str, Any]): Fields to update
        updated_by (Optional[str]): Updated by user

    Returns:
        bool: Whether update was successful
    """
    with get_db_session() as session:
        update_data = updates.copy()
        if updated_by:
            update_data["updated_by"] = updated_by

        result = session.query(RolePermission).filter(
            RolePermission.role_permission_id == role_permission_id,
            RolePermission.delete_flag == "N"
        ).update(update_data, synchronize_session=False)

        return result > 0


def soft_delete_role_permission(role_permission_id: int, updated_by: Optional[str] = None) -> bool:
    """
    Soft delete role permission

    Args:
        role_permission_id (int): Role permission ID
        updated_by (Optional[str]): Updated by user

    Returns:
        bool: Whether deletion was successful
    """
    with get_db_session() as session:
        update_data: Dict[str, Any] = {"delete_flag": "Y"}
        if updated_by:
            update_data["updated_by"] = updated_by

        result = session.query(RolePermission).filter(
            RolePermission.role_permission_id == role_permission_id,
            RolePermission.delete_flag == "N"
        ).update(update_data, synchronize_session=False)

        return result > 0


def delete_role_permissions_by_role(user_role: str, updated_by: Optional[str] = None) -> int:
    """
    Delete all permissions for a user role

    Args:
        user_role (str): User role
        updated_by (Optional[str]): Updated by user

    Returns:
        int: Number of deleted permissions
    """
    with get_db_session() as session:
        update_data: Dict[str, Any] = {"delete_flag": "Y"}
        if updated_by:
            update_data["updated_by"] = updated_by

        result = session.query(RolePermission).filter(
            RolePermission.user_role == user_role,
            RolePermission.delete_flag == "N"
        ).update(update_data, synchronize_session=False)

        return result


def check_role_permission(user_role: str, permission_category: Optional[str] = None,
                         permission_type: Optional[str] = None, permission_subtype: Optional[str] = None) -> bool:
    """
    Check if a role has specific permission

    Args:
        user_role (str): User role
        permission_category (Optional[str]): Permission category
        permission_type (Optional[str]): Permission type
        permission_subtype (Optional[str]): Permission subtype

    Returns:
        bool: Whether the role has the permission
    """
    with get_db_session() as session:
        query = session.query(RolePermission).filter(
            RolePermission.user_role == user_role,
            RolePermission.delete_flag == "N"
        )

        if permission_category:
            query = query.filter(RolePermission.permission_category == permission_category)
        if permission_type:
            query = query.filter(RolePermission.permission_type == permission_type)
        if permission_subtype:
            query = query.filter(RolePermission.permission_subtype == permission_subtype)

        result = query.first()
        return result is not None


def get_permissions_by_category(permission_category: str) -> List[Dict[str, Any]]:
    """
    Get all permissions for a specific category

    Args:
        permission_category (str): Permission category

    Returns:
        List[Dict[str, Any]]: List of role permission records
    """
    with get_db_session() as session:
        result = session.query(RolePermission).filter(
            RolePermission.permission_category == permission_category,
            RolePermission.delete_flag == "N"
        ).all()

        return [as_dict(record) for record in result]


def initialize_default_permissions() -> None:
    """
    Initialize default role permissions
    This should be called during system setup
    """
    default_permissions = [
        # SUPER_ADMIN permissions (SU)
        {"user_role": "SU", "permission_category": "SYSTEM", "permission_type": "ALL", "permission_subtype": "FULL_ACCESS"},
        # ADMIN permissions
        {"user_role": "ADMIN", "permission_category": "USER_MANAGEMENT", "permission_type": "USER", "permission_subtype": "CRUD"},
        {"user_role": "ADMIN", "permission_category": "GROUP_MANAGEMENT", "permission_type": "GROUP", "permission_subtype": "CRUD"},
        {"user_role": "ADMIN", "permission_category": "KNOWLEDGE_BASE", "permission_type": "KNOWLEDGE", "permission_subtype": "CRUD"},
        {"user_role": "ADMIN", "permission_category": "AGENT_MANAGEMENT", "permission_type": "AGENT", "permission_subtype": "CRUD"},
        {"user_role": "ADMIN", "permission_category": "INVITATION_MANAGEMENT", "permission_type": "INVITATION", "permission_subtype": "CRUD"},
        # DEV permissions
        {"user_role": "DEV", "permission_category": "KNOWLEDGE_BASE", "permission_type": "KNOWLEDGE", "permission_subtype": "READ"},
        {"user_role": "DEV", "permission_category": "KNOWLEDGE_BASE", "permission_type": "KNOWLEDGE", "permission_subtype": "CREATE"},
        {"user_role": "DEV", "permission_category": "AGENT_MANAGEMENT", "permission_type": "AGENT", "permission_subtype": "READ"},
        {"user_role": "DEV", "permission_category": "AGENT_MANAGEMENT", "permission_type": "AGENT", "permission_subtype": "CREATE"},
        # USER permissions
        {"user_role": "USER", "permission_category": "KNOWLEDGE_BASE", "permission_type": "KNOWLEDGE", "permission_subtype": "READ"},
        {"user_role": "USER", "permission_category": "AGENT_MANAGEMENT", "permission_type": "AGENT", "permission_subtype": "READ"},
    ]

    for permission in default_permissions:
        # Check if permission already exists
        if not check_role_permission(
            user_role=permission["user_role"],
            permission_category=permission["permission_category"],
            permission_type=permission["permission_type"],
            permission_subtype=permission["permission_subtype"]
        ):
            create_role_permission(
                user_role=permission["user_role"],
                permission_category=permission["permission_category"],
                permission_type=permission["permission_type"],
                permission_subtype=permission["permission_subtype"],
                created_by="SYSTEM"
            )
