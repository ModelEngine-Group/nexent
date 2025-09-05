"""
Database operations for user tenant relationship management
"""
from typing import Any, Dict, Optional

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
