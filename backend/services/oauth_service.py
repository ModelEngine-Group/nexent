import json
import logging
import os
import secrets
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, quote

from consts.const import DEFAULT_TENANT_ID, OAUTH_CALLBACK_BASE_URL
from consts.exceptions import OAuthLinkError, OAuthProviderError
from consts.oauth_providers import (
    get_all_provider_definitions,
    get_provider_definition,
    is_provider_enabled,
)
from database.oauth_account_db import (
    count_oauth_accounts_by_user_id,
    get_oauth_account_by_provider,
    insert_oauth_account,
    list_oauth_accounts_by_user_id,
    rebind_oauth_account,
    soft_delete_oauth_account,
    update_oauth_account_tokens,
)
from database.user_tenant_db import get_user_tenant_by_user_id, insert_user_tenant

logger = logging.getLogger(__name__)

_state_store: Dict[str, float] = {}


def parse_state(state: str) -> Dict[str, str]:
    parts = state.split(":", 2)
    if len(parts) >= 2:
        return {
            "provider": parts[0],
            "token": parts[1],
            "link_user_id": parts[2] if len(parts) > 2 else "",
        }
    return {"provider": state, "token": "", "link_user_id": ""}


def _resolve_field(data: dict, field_path: str) -> Any:
    if "." not in field_path:
        return data.get(field_path)
    parts = field_path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def get_supported_providers() -> set:
    return set(get_all_provider_definitions().keys())


def get_enabled_providers() -> List[Dict[str, str]]:
    providers = []
    for name, definition in get_all_provider_definitions().items():
        if is_provider_enabled(definition):
            providers.append(
                {
                    "name": definition.name,
                    "display_name": definition.display_name,
                    "icon": definition.icon,
                    "enabled": True,
                }
            )
    return providers


def get_authorize_url(provider: str, link_user_id: str = "") -> str:
    try:
        definition = get_provider_definition(provider)
    except KeyError:
        raise OAuthProviderError(f"Unsupported OAuth provider: {provider}")

    if not is_provider_enabled(definition):
        raise OAuthProviderError(f"OAuth provider '{provider}' is not configured")

    callback_url = (
        f"{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider={provider}"
    )
    random_token = secrets.token_urlsafe(32)
    if link_user_id:
        state = f"{provider}:{random_token}:{link_user_id}"
    else:
        state = f"{provider}:{random_token}"
    _state_store[state] = datetime.now().timestamp()

    client_id = os.getenv(definition.client_id_env, "")
    redirect_uri = (
        quote(callback_url, safe="") if definition.encode_redirect_uri else callback_url
    )

    params = dict(definition.authorize_params)
    param_map = definition.authorize_param_map
    params[param_map.get("client_id", "client_id")] = client_id
    params[param_map.get("redirect_uri", "redirect_uri")] = redirect_uri
    params[param_map.get("state", "state")] = state

    url = f"{definition.authorize_url}?{urlencode(params)}"
    if definition.authorize_fragment:
        url += definition.authorize_fragment
    return url


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
    try:
        definition = get_provider_definition(provider)
    except KeyError:
        raise OAuthProviderError(f"Unsupported provider: {provider}")

    client_id = os.getenv(definition.client_id_env, "")
    client_secret = os.getenv(definition.client_secret_env, "")
    callback_url = (
        f"{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider={provider}"
    )
    redirect_uri = (
        quote(callback_url, safe="") if definition.encode_redirect_uri else callback_url
    )

    param_map = definition.token_params_map

    result: Dict[str, Any] = {"access_token": ""}

    if definition.token_method.upper() == "POST":
        body = dict(definition.token_extra_params)
        body[param_map.get("client_id", "client_id")] = client_id
        body[param_map.get("client_secret", "client_secret")] = client_secret
        body[param_map.get("code", "code")] = code
        body.setdefault(param_map.get("grant_type", "grant_type"), "authorization_code")
        if param_map.get("redirect_uri", "") == "redirect_uri":
            body["redirect_uri"] = redirect_uri

        resp = _http_post_json(definition.token_url, data=body)
    else:
        params = dict(definition.token_extra_params)
        params[param_map.get("client_id", "client_id")] = client_id
        params[param_map.get("client_secret", "client_secret")] = client_secret
        params[param_map.get("code", "code")] = code
        params[param_map.get("grant_type", "grant_type")] = "authorization_code"
        if param_map.get("redirect_uri", "") == "redirect_uri":
            params["redirect_uri"] = redirect_uri

        resp = _http_get_json(f"{definition.token_url}?{urlencode(params)}")

    if definition.token_error_key and definition.token_error_key in resp:
        err_msg = resp.get(
            definition.token_error_message_key, str(resp[definition.token_error_key])
        )
        raise OAuthProviderError(f"{provider} token exchange failed: {err_msg}")

    result["access_token"] = resp["access_token"]
    if definition.token_response_id_key:
        result["openid"] = resp.get(definition.token_response_id_key, "")

    return result


def get_provider_user_info(
    provider: str, access_token: str, **kwargs: Any
) -> Dict[str, Any]:
    try:
        definition = get_provider_definition(provider)
    except KeyError:
        raise OAuthProviderError(f"Unsupported provider: {provider}")

    headers: Dict[str, str] = {"Accept": "application/json"}
    if definition.userinfo_auth_scheme and access_token:
        headers["Authorization"] = f"{definition.userinfo_auth_scheme} {access_token}"

    url_params = {}
    for key, value in definition.userinfo_params.items():
        resolved = value.format(
            openid=kwargs.get("openid", ""), access_token=access_token
        )
        url_params[key] = resolved

    query = urlencode(url_params) if url_params else ""
    separator = (
        "&" if "?" in definition.userinfo_url and query else ("?" if query else "")
    )
    url = f"{definition.userinfo_url}{separator}{query}"

    user_resp = _http_get_json(url, headers=headers)

    field_map = definition.userinfo_field_map
    result = {}
    for our_key, provider_key in field_map.items():
        if provider_key:
            result[our_key] = _resolve_field(user_resp, provider_key) or ""
        else:
            result[our_key] = ""
    result["id"] = str(result.get("id", ""))

    if definition.userinfo_needs_email_fetch and not result.get("email"):
        try:
            emails_resp = _http_get_json(
                definition.userinfo_email_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if isinstance(emails_resp, list) and emails_resp:
                primary = next(
                    (e for e in emails_resp if e.get("primary")),
                    emails_resp[0],
                )
                result["email"] = primary.get("email", "")
        except Exception:
            logger.warning(f"Failed to fetch {provider} user emails")
            result["email"] = f"{result['id']}@nexent.com"

    return result


def create_or_update_oauth_account(
    user_id: str,
    provider: str,
    provider_user_id: str,
    email: Optional[str] = None,
    username: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    existing = get_oauth_account_by_provider(provider, provider_user_id)

    if existing:
        if existing.get("user_id") != user_id:
            rebind_oauth_account(
                provider=provider,
                provider_user_id=provider_user_id,
                new_user_id=user_id,
                provider_email=email,
                provider_username=username,
                tenant_id=tenant_id or DEFAULT_TENANT_ID,
            )
        else:
            update_oauth_account_tokens(
                provider=provider,
                provider_user_id=provider_user_id,
                provider_username=username,
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
                "linked_at": str(acct.get("create_time", "")),
            }
        )
    return result


def unlink_account(
    user_id: str, provider: str, has_password_auth: bool = False
) -> bool:
    oauth_count = count_oauth_accounts_by_user_id(user_id)
    if oauth_count <= 1 and not has_password_auth:
        raise OAuthLinkError("Cannot unlink the last authentication method")

    success = soft_delete_oauth_account(user_id, provider)
    if not success:
        raise OAuthLinkError(f"No linked {provider} account found")
    return True
