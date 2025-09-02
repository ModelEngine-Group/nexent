"""
Database operations for user tenant relationship management
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

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
    try:
        with get_db_session() as session:
            result = session.query(UserTenant).filter(
                UserTenant.user_id == user_id,
                UserTenant.delete_flag == "N"
            ).first()

            if result:
                return as_dict(result)
            return None

    except SQLAlchemyError as e:
        logging.error(f"Error querying user tenant relationship: {str(e)}")
        return None


def insert_user_tenant(user_id: str, tenant_id: str, created_by: str = None) -> bool:
    """
    Insert user tenant relationship

    Args:
        user_id (str): User ID
        tenant_id (str): Tenant ID
        created_by (str): Creator ID

    Returns:
        bool: Whether insertion was successful
    """
    try:
        with get_db_session() as session:
            user_tenant = UserTenant(
                user_id=user_id,
                tenant_id=tenant_id,
                created_by=created_by or user_id,
                updated_by=created_by or user_id
            )

            session.add(user_tenant)
            session.flush()
            session.commit()
            logging.info(
                f"Successfully inserted user tenant relationship: user_id={user_id}, tenant_id={tenant_id}")
            return True

    except SQLAlchemyError as e:
        logging.error(f"Error inserting user tenant relationship: {str(e)}")
        return False


def get_users_by_tenant_id(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Get all users in a tenant

    Args:
        tenant_id (str): Tenant ID

    Returns:
        List[Dict[str, Any]]: List of user tenant relationships
    """
    try:
        with get_db_session() as session:
            results = session.query(UserTenant).filter(
                UserTenant.tenant_id == tenant_id,
                UserTenant.delete_flag == "N"
            ).all()

            return [as_dict(result) for result in results]

    except SQLAlchemyError as e:
        logging.error(f"Error querying users by tenant ID: {str(e)}")
        return []


def delete_user_tenant(user_id: str, tenant_id: str, updated_by: str = None) -> bool:
    """
    Soft delete user tenant relationship

    Args:
        user_id (str): User ID
        tenant_id (str): Tenant ID
        updated_by (str): Updater ID

    Returns:
        bool: Whether deletion was successful
    """
    try:
        with get_db_session() as session:
            result = session.query(UserTenant).filter(
                UserTenant.user_id == user_id,
                UserTenant.tenant_id == tenant_id,
                UserTenant.delete_flag == "N"
            ).first()

            if result:
                result.delete_flag = "Y"
                result.updated_by = updated_by or user_id
                session.flush()
                session.commit()
                logging.info(
                    f"Successfully deleted user tenant relationship: user_id={user_id}, tenant_id={tenant_id}")
                return True
            else:
                logging.warning(
                    f"User tenant relationship not found: user_id={user_id}, tenant_id={tenant_id}")
                return False

    except SQLAlchemyError as e:
        logging.error(f"Error deleting user tenant relationship: {str(e)}")
        return False
