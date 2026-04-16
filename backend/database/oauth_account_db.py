"""
Database operations for OAuth account management
"""

import logging
from typing import Any, Dict, List, Optional

from database.client import as_dict, get_db_session
from database.db_models import UserOAuthAccount

logger = logging.getLogger(__name__)


def insert_oauth_account(
    user_id: str,
    provider: str,
    provider_user_id: str,
    provider_email: Optional[str] = None,
    provider_username: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    with get_db_session() as session:
        account = UserOAuthAccount(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email,
            provider_username=provider_username,
            tenant_id=tenant_id,
            created_by=user_id,
            updated_by=user_id,
        )
        session.add(account)
        session.flush()
        return as_dict(account)


def get_oauth_account_by_provider(
    provider: str, provider_user_id: str
) -> Optional[Dict[str, Any]]:
    with get_db_session() as session:
        result = (
            session.query(UserOAuthAccount)
            .filter(
                UserOAuthAccount.provider == provider,
                UserOAuthAccount.provider_user_id == provider_user_id,
            )
            .first()
        )
        return as_dict(result) if result else None


def list_oauth_accounts_by_user_id(user_id: str) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        results = (
            session.query(UserOAuthAccount)
            .filter(UserOAuthAccount.user_id == user_id)
            .all()
        )
        return [as_dict(r) for r in results]


def rebind_oauth_account(
    provider: str,
    provider_user_id: str,
    new_user_id: str,
    provider_email: Optional[str] = None,
    provider_username: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> bool:
    with get_db_session() as session:
        result = (
            session.query(UserOAuthAccount)
            .filter(
                UserOAuthAccount.provider == provider,
                UserOAuthAccount.provider_user_id == provider_user_id,
            )
            .first()
        )
        if not result:
            return False

        result.user_id = new_user_id
        result.updated_by = new_user_id
        if provider_email is not None:
            result.provider_email = provider_email
        if provider_username is not None:
            result.provider_username = provider_username
        if tenant_id is not None:
            result.tenant_id = tenant_id

        return True


def update_oauth_account_tokens(
    provider: str,
    provider_user_id: str,
    provider_username: Optional[str] = None,
) -> bool:
    with get_db_session() as session:
        result = (
            session.query(UserOAuthAccount)
            .filter(
                UserOAuthAccount.provider == provider,
                UserOAuthAccount.provider_user_id == provider_user_id,
            )
            .first()
        )
        if not result:
            return False

        if provider_username is not None:
            result.provider_username = provider_username

        return True


def delete_oauth_account(user_id: str, provider: str) -> bool:
    with get_db_session() as session:
        result = (
            session.query(UserOAuthAccount)
            .filter(
                UserOAuthAccount.user_id == user_id,
                UserOAuthAccount.provider == provider,
            )
            .first()
        )
        if not result:
            return False

        session.delete(result)
        return True


def count_oauth_accounts_by_user_id(user_id: str) -> int:
    with get_db_session() as session:
        return (
            session.query(UserOAuthAccount)
            .filter(UserOAuthAccount.user_id == user_id)
            .count()
        )
