import json
import logging
import os
import secrets
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from consts.const import (
    CAS_CA_BUNDLE,
    CAS_CALLBACK_BASE_URL,
    CAS_EMAIL_ATTRIBUTE,
    CAS_ENABLED,
    CAS_LOGIN_MODE,
    CAS_LOGOUT_URL,
    CAS_RENEW_BEFORE_SECONDS,
    CAS_RENEW_TIMEOUT_SECONDS,
    CAS_ROLE_ATTRIBUTE,
    CAS_ROLE_MAP_JSON,
    CAS_SERVER_URL,
    CAS_SESSION_MAX_AGE_SECONDS,
    CAS_SSL_VERIFY,
    CAS_SYNTHETIC_EMAIL_DOMAIN,
    CAS_TENANT_ATTRIBUTE,
    CAS_USER_ATTRIBUTE,
    CAS_VALIDATE_PATH,
    DEFAULT_TENANT_ID,
    LOCAL_SESSION_MAX_AGE_SECONDS,
)
from database.cas_session_db import (
    create_cas_session,
    revoke_cas_session_by_index,
    revoke_cas_sessions_by_user_id,
)
from database.oauth_account_db import get_oauth_account_by_provider
from database.user_tenant_db import get_user_tenant_by_user_id, upsert_user_tenant
from services.oauth_service import (
    create_or_update_oauth_account,
    find_supabase_user_id_by_email,
)
from services.skill_service import init_skill_list_for_tenant
from services.tool_configuration_service import init_tool_list_for_tenant
from utils.auth_utils import calculate_expires_at, generate_session_jwt, get_supabase_admin_client

logger = logging.getLogger(__name__)

CAS_PROVIDER = "cas"
VALID_ROLES = {"SU", "ADMIN", "DEV", "USER"}


class CasAuthenticationError(Exception):
    pass


@dataclass
class CasPrincipal:
    cas_user_id: str
    email: str
    username: str
    role: str
    tenant_id: str
    session_index: str
    expires_at: datetime


def get_cas_config() -> Dict[str, Any]:
    mode = CAS_LOGIN_MODE if CAS_LOGIN_MODE in {"button", "force", "disabled"} else "disabled"
    enabled = CAS_ENABLED and bool(CAS_SERVER_URL)
    if not enabled:
        mode = "disabled"
    return {
        "enabled": enabled,
        "login_mode": mode,
        "renew_before_seconds": CAS_RENEW_BEFORE_SECONDS,
        "renew_timeout_seconds": CAS_RENEW_TIMEOUT_SECONDS,
        "display_name": "CAS",
    }


def build_login_url(redirect: str = "/") -> str:
    _ensure_enabled()
    service_url = _build_callback_url("/api/user/cas/callback", {"redirect": _normalize_redirect(redirect)})
    params = urllib.parse.urlencode({"service": service_url})
    return f"{CAS_SERVER_URL}/login?{params}"


def build_renew_url() -> str:
    _ensure_enabled()
    service_url = _build_callback_url("/api/user/cas/renew_callback", {})
    params = urllib.parse.urlencode({"service": service_url, "gateway": "true"})
    return f"{CAS_SERVER_URL}/login?{params}"


def build_logout_url() -> str:
    _ensure_enabled()
    configured_logout_url = CAS_LOGOUT_URL.strip()
    if not configured_logout_url:
        return ""

    parsed_config = urllib.parse.urlsplit(configured_logout_url)
    if parsed_config.scheme and parsed_config.netloc:
        logout_url = configured_logout_url
    else:
        logout_url = f"{CAS_SERVER_URL}/{configured_logout_url.lstrip('/')}"

    parsed = urllib.parse.urlsplit(logout_url)
    if parsed.query:
        return logout_url

    query = urllib.parse.urlencode({"service": f"{CAS_SERVER_URL}/login"})
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


async def login_with_ticket(ticket: str, redirect: str = "/") -> Dict[str, Any]:
    redirect = _normalize_redirect(redirect)
    service_url = _build_callback_url("/api/user/cas/callback", {"redirect": redirect})
    principal = validate_service_ticket(ticket, service_url)
    return await _create_project_session(principal, redirect=redirect)


async def renew_with_ticket(ticket: str) -> Dict[str, Any]:
    service_url = _build_callback_url("/api/user/cas/renew_callback", {})
    principal = validate_service_ticket(ticket, service_url)
    return await _create_project_session(principal, redirect="/", renew=True)


def validate_service_ticket(ticket: str, service_url: str) -> CasPrincipal:
    _ensure_enabled()
    if not ticket:
        raise CasAuthenticationError("CAS ticket is missing")

    validate_path = CAS_VALIDATE_PATH if CAS_VALIDATE_PATH.startswith("/") else f"/{CAS_VALIDATE_PATH}"
    validate_url = f"{CAS_SERVER_URL}{validate_path}"
    params = urllib.parse.urlencode({"service": service_url, "ticket": ticket})
    xml_text = _http_get_text(f"{validate_url}?{params}")
    return parse_service_validate_response(xml_text, fallback_session_index=ticket)


def parse_service_validate_response(xml_text: str, fallback_session_index: str = "") -> CasPrincipal:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise CasAuthenticationError("Invalid CAS validation response") from exc

    failure = _find_first(root, "authenticationFailure")
    if failure is not None:
        raise CasAuthenticationError((failure.text or "CAS authentication failed").strip())

    success = _find_first(root, "authenticationSuccess")
    if success is None:
        raise CasAuthenticationError("CAS authentication failed")

    user = _get_child_text(success, "user")
    attrs_node = _find_first(success, "attributes")
    attrs = _extract_attributes(attrs_node) if attrs_node is not None else {}

    cas_user_id = _attribute_or_default(attrs, CAS_USER_ATTRIBUTE, user) or user
    if not cas_user_id:
        raise CasAuthenticationError("CAS user id is missing")

    email = _attribute_or_default(attrs, CAS_EMAIL_ATTRIBUTE, "")
    username = attrs.get("displayName") or attrs.get("name") or cas_user_id
    role = _map_role(_attribute_or_default(attrs, CAS_ROLE_ATTRIBUTE, "USER"))
    tenant_id = _attribute_or_default(attrs, CAS_TENANT_ATTRIBUTE, DEFAULT_TENANT_ID) or DEFAULT_TENANT_ID
    session_index = attrs.get("SessionIndex") or attrs.get("sessionIndex") or fallback_session_index
    expires_at = _resolve_expires_at(attrs)

    if not email:
        safe_user = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in cas_user_id)
        email = f"{safe_user}@{CAS_SYNTHETIC_EMAIL_DOMAIN}"

    return CasPrincipal(
        cas_user_id=str(cas_user_id),
        email=str(email).lower(),
        username=str(username),
        role=role,
        tenant_id=str(tenant_id),
        session_index=str(session_index or ""),
        expires_at=expires_at,
    )


def parse_logout_request(logout_request: str) -> Dict[str, str]:
    if not logout_request:
        return {"cas_user_id": "", "session_index": ""}
    try:
        root = ET.fromstring(logout_request)
    except ET.ParseError:
        logger.warning("Invalid CAS logoutRequest XML")
        return {"cas_user_id": "", "session_index": ""}

    session_index = _get_child_text(root, "SessionIndex")
    cas_user_id = (
        _get_child_text(root, "NameID")
        or _get_child_text(root, "nameID")
        or _get_child_text(root, "user")
        or _get_child_text(root, "casUserId")
    )
    return {"cas_user_id": cas_user_id or "", "session_index": session_index or ""}


def revoke_from_logout_request(logout_request: str) -> Dict[str, Any]:
    parsed = parse_logout_request(logout_request)
    revoked = 0
    if parsed["cas_user_id"]:
        revoked = revoke_cas_sessions_by_user_id(parsed["cas_user_id"])
    elif parsed["session_index"]:
        revoked = revoke_cas_session_by_index(parsed["session_index"])
    return {"revoked": revoked, **parsed}


async def _create_project_session(principal: CasPrincipal, redirect: str = "/", renew: bool = False) -> Dict[str, Any]:
    user_id = _resolve_project_user(principal)
    existing_tenant = get_user_tenant_by_user_id(user_id)
    user_tenant = upsert_user_tenant(
        user_id=user_id,
        tenant_id=principal.tenant_id,
        user_role=principal.role,
        user_email=principal.email,
    )
    if not existing_tenant:
        await init_tool_list_for_tenant(principal.tenant_id, user_id)
        await init_skill_list_for_tenant(principal.tenant_id, user_id)

    now = datetime.now()
    max_local_expiry = now + timedelta(seconds=LOCAL_SESSION_MAX_AGE_SECONDS)
    expires_at_dt = min(principal.expires_at, max_local_expiry)
    expires_in_seconds = max(1, int((expires_at_dt - now).total_seconds()))

    session_id = secrets.token_urlsafe(32)
    create_cas_session(
        session_id=session_id,
        user_id=user_id,
        cas_user_id=principal.cas_user_id,
        cas_session_index=principal.session_index,
        expires_at=expires_at_dt,
    )

    jwt_token = generate_session_jwt(user_id, expires_in=expires_in_seconds, session_id=session_id)

    return {
        "user": {
            "id": str(user_id),
            "email": principal.email,
            "role": user_tenant.get("user_role", principal.role),
        },
        "session": {
            "access_token": jwt_token,
            "refresh_token": "",
            "expires_at": calculate_expires_at(jwt_token),
            "expires_in_seconds": expires_in_seconds,
        },
        "redirect_url": redirect,
        "renew": renew,
    }


def _resolve_project_user(principal: CasPrincipal) -> str:
    existing = get_oauth_account_by_provider(CAS_PROVIDER, principal.cas_user_id)
    if existing:
        create_or_update_oauth_account(
            user_id=existing["user_id"],
            provider=CAS_PROVIDER,
            provider_user_id=principal.cas_user_id,
            email=principal.email,
            username=principal.username,
            tenant_id=principal.tenant_id,
        )
        return existing["user_id"]

    admin_client = get_supabase_admin_client()
    if not admin_client:
        raise RuntimeError("Supabase admin client not available")

    user_id = find_supabase_user_id_by_email(admin_client, principal.email)
    if not user_id:
        create_resp = admin_client.auth.admin.create_user(
            {
                "email": principal.email,
                "password": secrets.token_urlsafe(32),
                "email_confirm": True,
                "user_metadata": {
                    "full_name": principal.username,
                    "provider": CAS_PROVIDER,
                    "cas_user_id": principal.cas_user_id,
                },
            }
        )
        user_id = create_resp.user.id

    create_or_update_oauth_account(
        user_id=user_id,
        provider=CAS_PROVIDER,
        provider_user_id=principal.cas_user_id,
        email=principal.email,
        username=principal.username,
        tenant_id=principal.tenant_id,
    )
    return user_id


def _ensure_enabled() -> None:
    if not CAS_ENABLED or not CAS_SERVER_URL:
        raise CasAuthenticationError("CAS is not configured")


def _build_callback_url(path: str, params: Dict[str, str]) -> str:
    if not CAS_CALLBACK_BASE_URL:
        raise CasAuthenticationError("CAS callback base URL is not configured")
    query = urllib.parse.urlencode(params)
    suffix = f"?{query}" if query else ""
    return f"{CAS_CALLBACK_BASE_URL}{path}{suffix}"


def _normalize_redirect(redirect: str) -> str:
    if not redirect or not redirect.startswith("/") or redirect.startswith("//"):
        return "/"
    return redirect


def _build_ssl_context() -> ssl.SSLContext:
    if CAS_CA_BUNDLE and os.path.isfile(CAS_CA_BUNDLE):
        return ssl.create_default_context(cafile=CAS_CA_BUNDLE)
    if not CAS_SSL_VERIFY:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()


def _http_get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"Accept": "application/xml,text/xml,*/*"})
    with urllib.request.urlopen(req, timeout=15, context=_build_ssl_context()) as resp:
        return resp.read().decode("utf-8")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_first(node: ET.Element, name: str) -> Optional[ET.Element]:
    for child in node.iter():
        if _local_name(child.tag) == name:
            return child
    return None


def _get_child_text(node: ET.Element, name: str) -> str:
    found = _find_first(node, name)
    return (found.text or "").strip() if found is not None else ""


def _extract_attributes(attrs_node: ET.Element) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for child in list(attrs_node):
        value = (child.text or "").strip()
        if value:
            attrs[_local_name(child.tag)] = value
    return attrs


def _attribute_or_default(attrs: Dict[str, str], key: str, default: str) -> str:
    if key and key in attrs:
        return attrs[key]
    return default


def _map_role(raw_role: str) -> str:
    role = (raw_role or "USER").upper()
    try:
        role_map = json.loads(CAS_ROLE_MAP_JSON) if CAS_ROLE_MAP_JSON else {}
        role = str(role_map.get(raw_role, role_map.get(role, role))).upper()
    except Exception:
        logger.warning("Invalid CAS_ROLE_MAP_JSON; falling back to raw role")
    return role if role in VALID_ROLES else "USER"


def _resolve_expires_at(attrs: Dict[str, str]) -> datetime:
    for key in ("expiresAt", "expirationDate", "validUntil", "notOnOrAfter"):
        value = attrs.get(key)
        if not value:
            continue
        parsed = _parse_datetime(value)
        if parsed:
            return parsed
    return datetime.now() + timedelta(seconds=CAS_SESSION_MAX_AGE_SECONDS)


def _parse_datetime(value: str) -> Optional[datetime]:
    try:
        if value.isdigit():
            timestamp = int(value)
            if timestamp > 10_000_000_000:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp)
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except Exception:
        return None
