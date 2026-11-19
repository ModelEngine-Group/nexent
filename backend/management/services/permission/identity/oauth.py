# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
import logging
import os
import secrets
import ssl
import time
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

import jwt
from pydantic import EmailStr, TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from contracts.authentication import PendingOAuthIdentity
from contracts.constants.constants import (
    ASSET_OWNER_ROLE,
    ASSET_OWNER_TENANT_ID,
    DEFAULT_TENANT_ID,
    OAUTH_PENDING_EXPIRE_SECONDS,
    OAUTH_PENDING_PURPOSE,
)
from contracts.constants.environment import GET_OAUTH_SETTING as get_oauth_setting
from contracts.constants.environment import (
    CASDOOR_SIGNUP_TENANT_ID,
    JWT_EXPIRY_SECONDS,
    JWT_SECRET,
    OAUTH_CA_BUNDLE,
    OAUTH_CALLBACK_BASE_URL,
    OAUTH_LOGIN_MODE,
    OAUTH_SSL_VERIFY,
)
from contracts.errors.exceptions import (
    AccountConflictError,
    IncorrectInviteCodeException,
    OAuthLinkError,
    OAuthProviderError,
    TenantResourceLimitError,
)
from contracts.roles import (
    has_any_role,
    invitation_roles,
    primary_role,
    roles_from_record,
)
from management.services.permission.identity.session import calculate_expires_at, generate_session_jwt
from management.utils.account_passwords import hash_password
from infrastructure.rdb.client import get_db_session
from management.db.identity.account import create_account, get_account_by_email
from management.db.identity.membership import lock_tenants
from management.db.identity.oauth_account import (
    delete_oauth_account,
    get_oauth_account_by_provider,
    get_soft_deleted_oauth_account,
    insert_oauth_account,
    list_oauth_accounts_by_user_id,
    reactivate_oauth_account,
    update_oauth_account_tokens,
)
from management.db.identity.user_tenant import (
    get_all_tenant_ids,
    get_user_tenant_by_user_id,
    insert_user_tenant,
)
from management.services.permission.asset_owner import require_asset_owner_enabled
from management.services.permission.identity.authentication import (
    validate_password_strength,
)
from management.services.permission.identity.invitations import (
    check_invitation_available,
    get_invitation_by_code,
)
from management.services.permission.identity.registration import (
    register_invited_account,
)
from management.services.tool.configuration import init_tool_list_for_tenant
from management.utils.oauth_providers import (
    get_all_provider_definitions,
    get_provider_definition,
    is_provider_enabled,
)

logger = logging.getLogger(__name__)

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


def _get_oauth_login_mode() -> str:
    if OAUTH_LOGIN_MODE in {"button", "force", "disabled"}:
        return OAUTH_LOGIN_MODE
    return "disabled"


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


def get_oauth_config() -> Dict[str, Any]:
    mode = _get_oauth_login_mode()
    providers = get_enabled_providers()
    auto_login_provider = None

    if mode == "force":
        if len(providers) == 1:
            auto_login_provider = providers[0]["name"]
        else:
            logger.warning(
                "OAuth auto login requires exactly one enabled provider; found %s",
                len(providers),
            )

    if not providers:
        mode = "disabled"

    return {
        "enabled": bool(providers),
        "login_mode": mode,
        "auto_login_provider": auto_login_provider,
        "providers": providers,
    }


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

    client_id = get_oauth_setting(definition.client_id_env, "")
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

    client_id = get_oauth_setting(definition.client_id_env, "")
    client_secret = get_oauth_setting(definition.client_secret_env, "")
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
    if not JWT_SECRET:
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
    from gateway.security.token_codec import encode_token

    return encode_token(payload, key=JWT_SECRET)


def get_pending_oauth_info(payload: PendingOAuthIdentity) -> Dict[str, Any]:
    provider_email = payload.get("provider_email") or ""
    return {
        "provider": payload["provider"],
        "provider_username": payload.get("provider_username") or "",
        "provider_email": provider_email,
        "email_required": not bool(provider_email),
        "password_required": payload["provider"] != "casdoor",
    }


def _validate_email(email: Optional[str]) -> str:
    if not email:
        raise OAuthLinkError("Email is required")
    try:
        return str(_EMAIL_ADAPTER.validate_python(email)).lower()
    except PydanticValidationError as exc:
        raise OAuthLinkError("Invalid email address") from exc


def find_account_user_id_by_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None

    account = get_account_by_email(email) if email else None
    return account["user_id"] if account else None


class CasdoorOnboardingError(OAuthLinkError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def onboard_casdoor_account(subject: str, email: str, username: str) -> str:
    """Provision a passwordless account, membership and binding in one transaction."""
    try:
        normalized_email = _validate_email(email)
    except OAuthLinkError as exc:
        raise CasdoorOnboardingError("casdoor_email_required", "Set an email in your Casdoor account") from exc

    tenant_id = CASDOOR_SIGNUP_TENANT_ID
    if not tenant_id or tenant_id in {DEFAULT_TENANT_ID, ASSET_OWNER_TENANT_ID} or tenant_id not in get_all_tenant_ids():
        raise CasdoorOnboardingError("casdoor_tenant_unavailable", "Casdoor sign-up tenant is not configured")

    try:
        with get_db_session() as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"casdoor-onboarding:{subject}"},
            )
            binding = get_oauth_account_by_provider("casdoor", subject, db_session=session)
            if binding:
                return binding["user_id"]
            if get_soft_deleted_oauth_account("casdoor", subject, db_session=session):
                raise CasdoorOnboardingError("casdoor_account_disabled", "Contact your administrator to restore access")
            lock_tenants(session, [tenant_id])
            account = create_account(normalized_email, db_session=session, auth_provider="casdoor")
            user_id = account["user_id"]
            insert_user_tenant(user_id, tenant_id, "USER", normalized_email, db_session=session)
            insert_oauth_account(
                user_id, "casdoor", subject, normalized_email, username, tenant_id, db_session=session
            )
            return user_id
    except (AccountConflictError, IntegrityError) as exc:
        binding = get_oauth_account_by_provider("casdoor", subject)
        if binding:
            return binding["user_id"]
        if not isinstance(exc, AccountConflictError):
            raise
        raise CasdoorOnboardingError(
            "casdoor_email_conflict", "The email is in use. Link Casdoor from the existing Nexent account."
        ) from exc


async def complete_pending_oauth_account(
    pending_identity: PendingOAuthIdentity,
    password: Optional[str],
    invite_code: str,
    email: Optional[str] = None,
) -> Dict[str, Any]:

    pending = pending_identity
    provider = pending["provider"]
    provider_user_id = pending["provider_user_id"]
    provider_email = pending.get("provider_email") or ""
    provider_username = pending.get("provider_username") or ""

    casdoor_only = provider == "casdoor"
    if not casdoor_only and len(password or "") < 6:
        raise OAuthLinkError("Password must be at least 6 characters")

    final_email = _validate_email(provider_email or email)
    normalized_invite_code = invite_code.strip().upper()

    if get_oauth_account_by_provider(provider, provider_user_id):
        raise OAuthLinkError(f"This {provider} account is already bound to another user")

    if not check_invitation_available(normalized_invite_code):
        raise OAuthLinkError("Invitation code is invalid or unavailable")

    invitation_info = get_invitation_by_code(normalized_invite_code)
    if not invitation_info:
        raise OAuthLinkError("Invitation code is invalid or unavailable")
    if not casdoor_only and not validate_password_strength(password):
        raise OAuthLinkError("Password must be at least 8 characters with uppercase, lowercase, and digit")
    if find_account_user_id_by_email(final_email):
        raise OAuthLinkError("Email already exists. Please log in first, then link this OAuth account in settings.")

    if has_any_role(invitation_roles(invitation_info), {ASSET_OWNER_ROLE}):
        require_asset_owner_enabled()
    account_options = {"auth_provider": "casdoor"} if casdoor_only else {}
    try:
        account, member = register_invited_account(
            final_email, None if casdoor_only else hash_password(password), normalized_invite_code, **account_options
        )
    except IncorrectInviteCodeException as exc:
        raise OAuthLinkError("Invitation code is invalid or unavailable") from exc
    except AccountConflictError as exc:
        raise OAuthLinkError("Email already exists. Please log in first, then link this OAuth account in settings.") from exc
    user_id = account["user_id"]
    tenant_id = member["tenant_id"]
    assigned_roles = roles_from_record(member)
    user_role = primary_role(assigned_roles)

    if not has_any_role(assigned_roles, {ASSET_OWNER_ROLE}):
        await init_tool_list_for_tenant(tenant_id, user_id)

    create_or_update_oauth_account(
        user_id=user_id,
        provider=provider,
        provider_user_id=provider_user_id,
        email=final_email,
        username=provider_username,
        tenant_id=tenant_id,
    )

    jwt_token = generate_session_jwt(
        user_id, expires_in=JWT_EXPIRY_SECONDS
    )
    expiry_seconds = JWT_EXPIRY_SECONDS
    expires_at = calculate_expires_at(jwt_token)

    return {
        "user": {
            "id": str(user_id),
            "email": final_email,
            "role": user_role,
            "roles": list(assigned_roles),
        },
        "session": {
            "access_token": jwt_token,
            "refresh_token": "",
            "expires_at": expires_at,
            "expires_in_seconds": expiry_seconds,
        },
    }


def require_provider_authentication(account: Dict[str, Any], provider: str) -> None:
    """Enforce the login provider recorded when a Casdoor-only account was created."""
    metadata = account.get("source_metadata") if isinstance(account, dict) else None
    if isinstance(metadata, dict) and metadata.get("auth_provider") == "casdoor" and provider != "casdoor":
        raise OAuthLinkError("This account only supports Casdoor login")


def require_provider_unlink(account: Dict[str, Any], provider: str) -> None:
    """Preserve the required login method of a Casdoor-only account."""
    metadata = account.get("source_metadata") if isinstance(account, dict) else None
    if isinstance(metadata, dict) and metadata.get("auth_provider") == "casdoor" and provider == "casdoor":
        raise OAuthLinkError("Cannot unlink the required Casdoor login")


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
