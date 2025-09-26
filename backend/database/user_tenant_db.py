"""
Database operations for user tenant relationship management
"""
from typing import Any, Dict, Optional

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


def insert_user_tenant(user_id: str, tenant_id: str):
    """
    Insert user tenant relationship

    Args:
        user_id (str): User ID
        tenant_id (str): Tenant ID
    """
    with get_db_session() as session:
        user_tenant = UserTenant(
            user_id=user_id,
            tenant_id=tenant_id,
            created_by=user_id,
            updated_by=user_id
        )
        session.add(user_tenant)


def soft_delete_user_tenant_by_user_id(user_id: str, actor: Optional[str] = None) -> bool:
    """
    Soft delete user-tenant relationship(s) for the specified user.

    Args:
        user_id: User ID
        actor: Updated_by field value

    Returns:
        bool: Whether any rows were affected
    """
    with get_db_session() as session:
        # Build soft-delete update
        update_data: Dict[str, Any] = {"delete_flag": "Y"}
        if actor:
            update_data["updated_by"] = actor

        result = (
            session.query(UserTenant)
            .filter(UserTenant.user_id == user_id, UserTenant.delete_flag == "N")
            .update(update_data, synchronize_session=False)
        )

        return result > 0
