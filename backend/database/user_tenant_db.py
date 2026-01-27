"""
Database operations for user tenant relationship management
"""
from typing import Any, List, Dict, Optional

from consts.const import DEFAULT_TENANT_ID
from database.client import as_dict, get_db_session
from database.db_models import UserTenant


def get_user_tenant_by_user_id(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get user tenant relationship by user ID

    Args:
        user_id (str): User ID

    Returns:
        Optional[Dict[str, Any]]: User tenant relationship record
    """
    with get_db_session() as session:
        result = session.query(UserTenant).filter(
            UserTenant.user_id == user_id,
            UserTenant.delete_flag == "N"
        ).first()

        if result:
            return as_dict(result)
        return None


def get_all_tenant_ids() -> list[str]:
    """
    Get all unique tenant IDs from the database

    Returns:
        list[str]: List of unique tenant IDs
    """
    with get_db_session() as session:
        result = session.query(UserTenant.tenant_id).filter(
            UserTenant.delete_flag == "N"
        ).distinct().all()

        tenant_ids = [row[0] for row in result]

        # Add default tenant_id if not already in the list
        if DEFAULT_TENANT_ID not in tenant_ids:
            tenant_ids.append(DEFAULT_TENANT_ID)

        return tenant_ids


def insert_user_tenant(user_id: str, tenant_id: str, user_role: str = "USER", user_email: str = None):
    """
    Insert user tenant relationship

    Args:
        user_id (str): User ID
        tenant_id (str): Tenant ID
        user_role (str): User role (SUPER_ADMIN, ADMIN, DEV, USER)
        user_email (str): User email address
    """
    with get_db_session() as session:
        user_tenant = UserTenant(
            user_id=user_id,
            tenant_id=tenant_id,
            user_role=user_role,
            user_email=user_email,
            created_by=user_id,
            updated_by=user_id
        )
        session.add(user_tenant)


def get_users_by_tenant_id(tenant_id: str, page: int = 1, page_size: int = 20,
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
        Dict[str, Any]: Dictionary containing users list and total count
    """
    with get_db_session() as session:
        # Get total count
        total_count = session.query(UserTenant).filter(
            UserTenant.tenant_id == tenant_id,
            UserTenant.delete_flag == "N"
        ).count()

        # Build base query
        query = session.query(UserTenant).filter(
            UserTenant.tenant_id == tenant_id,
            UserTenant.delete_flag == "N"
        )

        # Add sorting
        if sort_by == "created_at":
            if sort_order == "desc":
                query = query.order_by(UserTenant.create_time.desc())
            else:
                query = query.order_by(UserTenant.create_time.asc())

        # Get paginated results
        offset = (page - 1) * page_size
        results = query.offset(offset).limit(page_size).all()

        return {
            "users": [as_dict(row) for row in results],
            "total": total_count
        }


def update_user_tenant_role(user_id: str, role: str, updated_by: str) -> bool:
    """
    Update user role in user_tenant table

    Args:
        user_id (str): User ID
        role (str): New role
        updated_by (str): User who made the update

    Returns:
        bool: True if update successful, False otherwise
    """
    with get_db_session() as session:
        result = session.query(UserTenant).filter(
            UserTenant.user_id == user_id,
            UserTenant.delete_flag == "N"
        ).update({
            "user_role": role,
            "updated_by": updated_by,
            "update_time": "NOW()"  # This will be handled by the database trigger
        })

        return result > 0


def soft_delete_user_tenant_by_user_id(user_id: str, deleted_by: str) -> bool:
    """
    Soft delete user tenant relationship by user ID

    Args:
        user_id (str): User ID to delete
        deleted_by (str): User who performed the deletion

    Returns:
        bool: True if any records were deleted
    """
    with get_db_session() as session:
        result = session.query(UserTenant).filter(
            UserTenant.user_id == user_id,
            UserTenant.delete_flag == "N"
        ).update({
            "delete_flag": "Y",
            "updated_by": deleted_by,
            "update_time": "NOW()"
        })

        return result > 0
