"""
OAuth service - provider configuration, callback handling, account linking.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from consts.const import (
    DEFAULT_TENANT_ID,
    ENABLE_WECHAT_OAUTH,
    GITHUB_OAUTH_CLIENT_ID,
    GITHUB_OAUTH_CLIENT_SECRET,
    OAUTH_CALLBACK_BASE_URL,
    SUPABASE_URL,
    WECHAT_OAUTH_APP_ID,
    WECHAT_OAUTH_APP_SECRET,
)
from consts.exceptions import OAuthLinkError, OAuthProviderError
from database.oauth_account_db import (
    count_oauth_accounts_by_user_id,
    get_oauth_account_by_provider,
    insert_oauth_account,
    list_oauth_accounts_by_user_id,
    soft_delete_oauth_account,
    update_oauth_account_tokens,
)
from database.user_tenant_db import get_user_tenant_by_user_id, insert_user_tenant
from utils.token_encryption import encrypt_token

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = {"github", "wechat"}


def get_enabled_providers() -> List[Dict[str, str]]:
    providers = []

    if GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET:
        providers.append(
            {
                "name": "github",
                "display_name": "GitHub",
                "icon": "github",
                "enabled": True,
            }
        )

    if ENABLE_WECHAT_OAUTH and WECHAT_OAUTH_APP_ID and WECHAT_OAUTH_APP_SECRET:
        providers.append(
            {
                "name": "wechat",
                "display_name": "WeChat",
                "icon": "wechat",
                "enabled": True,
            }
        )

    return providers


def get_authorize_url(provider: str) -> str:
    if provider not in SUPPORTED_PROVIDERS:
        raise OAuthProviderError(f"Unsupported OAuth provider: {provider}")

    enabled = get_enabled_providers()
    if not any(p["name"] == provider for p in enabled):
        raise OAuthProviderError(f"OAuth provider '{provider}' is not configured")

    callback_url = (
        f"{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider={provider}"
    )
    params = {
        "provider": provider,
        "redirect_to": callback_url,
    }

    return f"{SUPABASE_URL}/auth/v1/authorize?{urlencode(params)}"


def create_or_update_oauth_account(
    user_id: str,
    provider: str,
    provider_user_id: str,
    email: Optional[str] = None,
    username: Optional[str] = None,
    avatar_url: Optional[str] = None,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    token_expires_at: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    existing = get_oauth_account_by_provider(provider, provider_user_id)

    encrypted_access = encrypt_token(access_token) if access_token else None
    encrypted_refresh = encrypt_token(refresh_token) if refresh_token else None

    if existing:
        update_oauth_account_tokens(
            provider=provider,
            provider_user_id=provider_user_id,
            access_token=encrypted_access,
            refresh_token=encrypted_refresh,
            token_expires_at=token_expires_at,
            provider_username=username,
            provider_avatar_url=avatar_url,
        )
        updated = get_oauth_account_by_provider(provider, provider_user_id)
        return updated if updated else existing
    else:
        return insert_oauth_account(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=email,
            provider_username=username,
            provider_avatar_url=avatar_url,
            access_token=encrypted_access,
            refresh_token=encrypted_refresh,
            token_expires_at=token_expires_at,
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
        )


def ensure_user_tenant_exists(user_id: str, email: str) -> Dict[str, Any]:
    existing = get_user_tenant_by_user_id(user_id)
    if existing:
        return existing

    insert_user_tenant(
        user_id=user_id,
        tenant_id=DEFAULT_TENANT_ID,
        user_role="USER",
        user_email=email,
    )
    logger.info(f"Created user_tenant for new OAuth user {user_id}")
    result = get_user_tenant_by_user_id(user_id)
    return result if result else {"user_id": user_id, "tenant_id": DEFAULT_TENANT_ID}


def list_linked_accounts(user_id: str) -> List[Dict[str, Any]]:
    accounts = list_oauth_accounts_by_user_id(user_id)
    result = []
    for acct in accounts:
        result.append(
            {
                "provider": acct["provider"],
                "provider_username": acct.get("provider_username"),
                "provider_email": acct.get("provider_email"),
                "provider_avatar_url": acct.get("provider_avatar_url"),
                "linked_at": str(acct.get("create_time", "")),
            }
        )
    return result


def unlink_account(user_id: str, provider: str) -> bool:
    oauth_count = count_oauth_accounts_by_user_id(user_id)
    if oauth_count <= 1:
        raise OAuthLinkError("Cannot unlink the last authentication method")

    success = soft_delete_oauth_account(user_id, provider)
    if not success:
        raise OAuthLinkError(f"No linked {provider} account found")
    return True
