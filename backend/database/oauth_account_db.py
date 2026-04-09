"""
Database operations for OAuth account management
"""

import logging
from datetime import datetime
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
    provider_avatar_url: Optional[str] = None,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    token_expires_at: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    with get_db_session() as session:
        account = UserOAuthAccount(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email,
            provider_username=provider_username,
            provider_avatar_url=provider_avatar_url,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
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
                UserOAuthAccount.delete_flag == "N",
            )
            .first()
        )
        return as_dict(result) if result else None


def list_oauth_accounts_by_user_id(user_id: str) -> List[Dict[str, Any]]:
    with get_db_session() as session:
        results = (
            session.query(UserOAuthAccount)
            .filter(
                UserOAuthAccount.user_id == user_id,
                UserOAuthAccount.delete_flag == "N",
            )
            .all()
        )
        return [as_dict(r) for r in results]


def update_oauth_account_tokens(
    provider: str,
    provider_user_id: str,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    token_expires_at: Optional[datetime] = None,
    provider_username: Optional[str] = None,
    provider_avatar_url: Optional[str] = None,
) -> bool:
    with get_db_session() as session:
        result = (
            session.query(UserOAuthAccount)
            .filter(
                UserOAuthAccount.provider == provider,
                UserOAuthAccount.provider_user_id == provider_user_id,
                UserOAuthAccount.delete_flag == "N",
            )
            .first()
        )
        if not result:
            return False

        if access_token is not None:
            result.access_token = access_token
        if refresh_token is not None:
            result.refresh_token = refresh_token
        if token_expires_at is not None:
            result.token_expires_at = token_expires_at
        if provider_username is not None:
            result.provider_username = provider_username
        if provider_avatar_url is not None:
            result.provider_avatar_url = provider_avatar_url

        return True


def soft_delete_oauth_account(user_id: str, provider: str) -> bool:
    with get_db_session() as session:
        result = (
            session.query(UserOAuthAccount)
            .filter(
                UserOAuthAccount.user_id == user_id,
                UserOAuthAccount.provider == provider,
                UserOAuthAccount.delete_flag == "N",
            )
            .first()
        )
        if not result:
            return False

        result.delete_flag = "Y"
        return True


def count_oauth_accounts_by_user_id(user_id: str) -> int:
    with get_db_session() as session:
        return (
            session.query(UserOAuthAccount)
            .filter(
                UserOAuthAccount.user_id == user_id,
                UserOAuthAccount.delete_flag == "N",
            )
            .count()
        )
