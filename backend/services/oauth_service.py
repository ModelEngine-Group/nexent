"""
OAuth service - provider configuration, token exchange, account linking.
"""

import json
import logging
import secrets
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, quote

from consts.const import (
    DEFAULT_TENANT_ID,
    ENABLE_WECHAT_OAUTH,
    GITHUB_OAUTH_CLIENT_ID,
    GITHUB_OAUTH_CLIENT_SECRET,
    OAUTH_CALLBACK_BASE_URL,
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

# In-memory state store for CSRF protection (single-instance deployment)
_state_store: Dict[str, float] = {}


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
    state = f"{provider}:{secrets.token_urlsafe(32)}"
    _state_store[state] = datetime.now().timestamp()

    if provider == "github":
        params = {
            "client_id": GITHUB_OAUTH_CLIENT_ID,
            "redirect_uri": callback_url,
            "scope": "read:user user:email",
            "state": state,
        }
        return f"https://github.com/login/oauth/authorize?{urlencode(params)}"

    if provider == "wechat":
        params = {
            "appid": WECHAT_OAUTH_APP_ID,
            "redirect_uri": quote(callback_url, safe=""),
            "response_type": "code",
            "scope": "snsapi_login",
            "state": state,
        }
        return f"https://open.weixin.qq.com/connect/qrconnect?{urlencode(params)}#wechat_redirect"

    raise OAuthProviderError(f"Unsupported OAuth provider: {provider}")


def _http_post_json(url: str, data: dict, headers: Optional[dict] = None) -> dict:
    req_data = json.dumps(data).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=req_data, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_json(url: str, headers: Optional[dict] = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def exchange_code_for_provider_token(provider: str, code: str) -> Dict[str, Any]:
    if provider == "github":
        resp = _http_post_json(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": GITHUB_OAUTH_CLIENT_ID,
                "client_secret": GITHUB_OAUTH_CLIENT_SECRET,
                "code": code,
            },
        )
        if "error" in resp:
            raise OAuthProviderError(
                f"GitHub token exchange failed: {resp.get('error_description', resp['error'])}"
            )
        return {"access_token": resp["access_token"]}

    if provider == "wechat":
        params = urlencode(
            {
                "appid": WECHAT_OAUTH_APP_ID,
                "secret": WECHAT_OAUTH_APP_SECRET,
                "code": code,
                "grant_type": "authorization_code",
            }
        )
        resp = _http_get_json(
            f"https://api.weixin.qq.com/sns/oauth2/access_token?{params}"
        )
        if "errcode" in resp:
            raise OAuthProviderError(
                f"WeChat token exchange failed: {resp.get('errmsg', str(resp['errcode']))}"
            )
        return {
            "access_token": resp["access_token"],
            "openid": resp["openid"],
        }

    raise OAuthProviderError(f"Unsupported provider: {provider}")


def get_provider_user_info(
    provider: str, access_token: str, **kwargs: Any
) -> Dict[str, Any]:
    if provider == "github":
        user_resp = _http_get_json(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        email = user_resp.get("email")
        if not email:
            try:
                emails_resp = _http_get_json(
                    "https://api.github.com/user/emails",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                primary = next(
                    (e for e in emails_resp if e.get("primary")),
                    emails_resp[0] if emails_resp else {},
                )
                email = primary.get("email")
            except Exception:
                logger.warning("Failed to fetch GitHub user emails")

        return {
            "id": str(user_resp["id"]),
            "email": email or "",
            "username": user_resp.get("login", ""),
            "avatar_url": user_resp.get("avatar_url", ""),
        }

    if provider == "wechat":
        openid = kwargs.get("openid", "")
        resp = _http_get_json(
            f"https://api.weixin.qq.com/sns/userinfo?access_token={access_token}&openid={openid}",
        )
        return {
            "id": resp.get("openid", openid),
            "email": "",
            "username": resp.get("nickname", ""),
            "avatar_url": resp.get("headimgurl", ""),
        }

    raise OAuthProviderError(f"Unsupported provider: {provider}")


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
