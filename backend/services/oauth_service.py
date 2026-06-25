import json
import logging
import os
import secrets
import ssl
import time
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, quote

import jwt
from pydantic import EmailStr, TypeAdapter, ValidationError as PydanticValidationError

from consts.const import (
    ASSET_OWNER_INVITE_CODE_TYPE,
    ASSET_OWNER_ROLE,
    ASSET_OWNER_TENANT_ID,
    DEFAULT_TENANT_ID,
    OAUTH_CALLBACK_BASE_URL,
    OAUTH_SSL_VERIFY,
    OAUTH_CA_BUNDLE,
    SUPABASE_JWT_SECRET,
)
from consts.exceptions import OAuthLinkError, OAuthProviderError
from services.asset_owner_visibility import require_asset_owner_enabled
from consts.oauth_providers import (
    get_all_provider_definitions,
    get_provider_definition,
    is_provider_enabled,
)
from database.oauth_account_db import (
    delete_oauth_account,
    get_oauth_account_by_provider,
    get_soft_deleted_oauth_account,
    insert_oauth_account,
    list_oauth_accounts_by_user_id,
    reactivate_oauth_account,
    update_oauth_account_tokens,
)
from database.user_tenant_db import get_user_tenant_by_user_id, insert_user_tenant

logger = logging.getLogger(__name__)

OAUTH_PENDING_EXPIRE_SECONDS = 10 * 60
OAUTH_PENDING_PURPOSE = "oauth_account_completion"
_EMAIL_ADAPTER = TypeAdapter(EmailStr)


def _build_ssl_context() -> ssl.SSLContext:
    if OAUTH_CA_BUNDLE and os.path.isfile(OAUTH_CA_BUNDLE):
        return ssl.create_default_context(cafile=OAUTH_CA_BUNDLE)
    if not OAUTH_SSL_VERIFY:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()


_SSL_CTX = _build_ssl_context()


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
    with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_json(url: str, headers: Optional[dict] = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
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

    return result


def generate_pending_oauth_token(
    provider: str,
    provider_user_id: str,
    provider_email: Optional[str] = None,
    provider_username: Optional[str] = None,
    expires_in: int = OAUTH_PENDING_EXPIRE_SECONDS,
) -> str:
    if not SUPABASE_JWT_SECRET:
        raise OAuthProviderError("JWT verification is not configured")

    now = int(time.time())
    payload = {
        "purpose": OAUTH_PENDING_PURPOSE,
        "provider": provider,
        "provider_user_id": provider_user_id,
        "provider_email": provider_email or "",
        "provider_username": provider_username or "",
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")


def parse_pending_oauth_token(pending_token: str) -> Dict[str, str]:
    if not pending_token:
        raise OAuthLinkError("OAuth account completion session is missing")
    if not SUPABASE_JWT_SECRET:
        raise OAuthProviderError("JWT verification is not configured")

    try:
        payload = jwt.decode(
            pending_token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_exp": True, "verify_aud": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise OAuthLinkError("OAuth account completion session has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise OAuthLinkError("OAuth account completion session is invalid") from exc

    if payload.get("purpose") != OAUTH_PENDING_PURPOSE:
        raise OAuthLinkError("OAuth account completion session is invalid")
    if not payload.get("provider") or not payload.get("provider_user_id"):
        raise OAuthLinkError("OAuth account completion session is incomplete")

    return {
        "provider": str(payload.get("provider", "")),
        "provider_user_id": str(payload.get("provider_user_id", "")),
        "provider_email": str(payload.get("provider_email", "")),
        "provider_username": str(payload.get("provider_username", "")),
    }


def get_pending_oauth_info(pending_token: str) -> Dict[str, Any]:
    payload = parse_pending_oauth_token(pending_token)
    provider_email = payload.get("provider_email") or ""
    return {
        "provider": payload["provider"],
        "provider_username": payload.get("provider_username") or "",
        "provider_email": provider_email,
        "email_required": not bool(provider_email),
    }


def _validate_email(email: Optional[str]) -> str:
    if not email:
        raise OAuthLinkError("Email is required")
    try:
        return str(_EMAIL_ADAPTER.validate_python(email)).lower()
    except PydanticValidationError as exc:
        raise OAuthLinkError("Invalid email address") from exc


def find_supabase_user_id_by_email(
    admin_client: Any, email: Optional[str]
) -> Optional[str]:
    if not email:
        return None

    page = 1
    while True:
        users_resp = admin_client.auth.admin.list_users(page=page, per_page=100)
        users = getattr(users_resp, "users", users_resp)
        if users is None:
            users = []
        if not users:
            return None
        for user in users:
            user_email = getattr(user, "email", "")
            if user_email and user_email.lower() == email.lower():
                return user.id
        if len(users) < 100:
            return None
        page += 1


def _role_from_invitation_type(code_type: str) -> str:
    if code_type == "ADMIN_INVITE":
        return "ADMIN"
    if code_type == "DEV_INVITE":
        return "DEV"
    if code_type == ASSET_OWNER_INVITE_CODE_TYPE:
        require_asset_owner_enabled()
        return ASSET_OWNER_ROLE
    return "USER"


async def complete_pending_oauth_account(
    pending_token: str,
    password: str,
    invite_code: str,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    from services.group_service import add_user_to_groups
    from services.invitation_service import (
        check_invitation_available,
        get_invitation_by_code,
        use_invitation_code,
    )
    from services.tool_configuration_service import init_tool_list_for_tenant
    from services.user_management_service import generate_tts_stt_4_admin
    from utils.auth_utils import calculate_expires_at, generate_session_jwt

    pending = parse_pending_oauth_token(pending_token)
    provider = pending["provider"]
    provider_user_id = pending["provider_user_id"]
    provider_email = pending.get("provider_email") or ""
    provider_username = pending.get("provider_username") or ""

    if len(password or "") < 6:
        raise OAuthLinkError("Password must be at least 6 characters")

    final_email = _validate_email(provider_email or email)
    normalized_invite_code = invite_code.upper()

    if get_oauth_account_by_provider(provider, provider_user_id):
        raise OAuthLinkError(f"This {provider} account is already bound to another user")

    if not check_invitation_available(normalized_invite_code):
        raise OAuthLinkError("Invitation code is invalid or unavailable")

    invitation_info = get_invitation_by_code(normalized_invite_code)
    if not invitation_info:
        raise OAuthLinkError("Invitation code is invalid or unavailable")

    admin_client = None
    try:
        from utils.auth_utils import get_supabase_admin_client

        admin_client = get_supabase_admin_client()
    except Exception:
        admin_client = None
    if not admin_client:
        raise RuntimeError("Supabase admin client not available")

    existing_user_id = find_supabase_user_id_by_email(admin_client, final_email)
    if existing_user_id:
        raise OAuthLinkError(
            "Email already exists. Please log in with email and password, "
            "then link this OAuth account in settings."
        )

    create_resp = admin_client.auth.admin.create_user(
        {
            "email": final_email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {
                "full_name": provider_username,
                "provider": provider,
            },
        }
    )
    supabase_user_id = create_resp.user.id

    tenant_id = invitation_info["tenant_id"]
    if invitation_info.get("code_type") == ASSET_OWNER_INVITE_CODE_TYPE:
        tenant_id = ASSET_OWNER_TENANT_ID
    user_role = _role_from_invitation_type(invitation_info.get("code_type", "USER_INVITE"))
    is_asset_owner_registration = user_role == ASSET_OWNER_ROLE

    insert_user_tenant(
        user_id=supabase_user_id,
        tenant_id=tenant_id,
        user_role=user_role,
        user_email=final_email,
    )

    invitation_result = use_invitation_code(normalized_invite_code, supabase_user_id)
    group_ids = invitation_result.get("group_ids", [])
    if isinstance(group_ids, str):
        from utils.str_utils import convert_string_to_list

        group_ids = convert_string_to_list(group_ids)
    if group_ids and not is_asset_owner_registration:
        add_user_to_groups(supabase_user_id, group_ids, supabase_user_id)

    if user_role == "ADMIN":
        await generate_tts_stt_4_admin(tenant_id, supabase_user_id)
    if not is_asset_owner_registration:
        await init_tool_list_for_tenant(tenant_id, supabase_user_id)

    create_or_update_oauth_account(
        user_id=supabase_user_id,
        provider=provider,
        provider_user_id=provider_user_id,
        email=final_email,
        username=provider_username,
        tenant_id=tenant_id,
    )

    expiry_seconds = 3600
    jwt_token = generate_session_jwt(supabase_user_id, expires_in=expiry_seconds)
    expires_at = calculate_expires_at(jwt_token)

    return {
        "user": {
            "id": str(supabase_user_id),
            "email": final_email,
            "role": user_role,
        },
        "session": {
            "access_token": jwt_token,
            "refresh_token": "",
            "expires_at": expires_at,
            "expires_in_seconds": expiry_seconds,
        },
    }


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
            raise OAuthLinkError(
                f"This {provider} account is already bound to another user"
            )
        else:
            update_oauth_account_tokens(
                provider=provider,
                provider_user_id=provider_user_id,
                provider_username=username,
            )
        updated = get_oauth_account_by_provider(provider, provider_user_id)
        return updated if updated else existing

    soft_deleted = get_soft_deleted_oauth_account(provider, provider_user_id)
    if soft_deleted:
        reactivate_oauth_account(
            provider=provider,
            provider_user_id=provider_user_id,
            user_id=user_id,
            provider_email=email,
            provider_username=username,
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
        )
        reactivated = get_oauth_account_by_provider(provider, provider_user_id)
        return reactivated if reactivated else {"provider": provider, "provider_user_id": provider_user_id, "user_id": user_id}

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


def unlink_account(user_id: str, provider: str) -> bool:
    success = delete_oauth_account(user_id, provider)
    if not success:
        raise OAuthLinkError(f"No linked {provider} account found")
    return True
