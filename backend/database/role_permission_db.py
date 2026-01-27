"""
Database operations for role permission management
"""
from typing import Any, Dict, List, Optional

from database.client import as_dict, get_db_session
from database.db_models import RolePermission




def get_all_role_permissions() -> List[Dict[str, Any]]:
    """
    Get all role permissions

    Returns:
        List[Dict[str, Any]]: List of all role permission records
    """
    with get_db_session() as session:
        result = session.query(RolePermission).all()

        return [as_dict(record) for record in result]


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
            RolePermission.user_role == user_role
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
            RolePermission.permission_category == permission_category
        ).all()

        return [as_dict(record) for record in result]
