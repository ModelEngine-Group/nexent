"""
Keycloak Admin API helper for session management.

This module provides server-side Keycloak session termination via the Admin REST API,
which is more reliable than the front-channel OIDC logout endpoint on Keycloak 12.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from consts.const import (
    KEYCLOAK_ADMIN_CLIENT_ID,
    KEYCLOAK_ADMIN_PASSWORD,
    KEYCLOAK_ADMIN_USERNAME,
    KEYCLOAK_REALM,
    KEYCLOAK_URL,
    OAUTH_CA_BUNDLE,
    OAUTH_SSL_VERIFY,
)
from database.user_tenant_db import get_user_tenant_by_user_id

logger = logging.getLogger(__name__)

_SSL_CTX = None
if not OAUTH_SSL_VERIFY:
    import ssl

    _ctx = ssl.create_default_context()
    _ctx.check_hostname = False
    _ctx.verify_mode = ssl.CERT_NONE
    _SSL_CTX = _ctx
elif OAUTH_CA_BUNDLE:
    import ssl

    _ctx = ssl.create_default_context(cafile=OAUTH_CA_BUNDLE)
    _SSL_CTX = _ctx


def _build_admin_url(path: str) -> str:
    return f"{KEYCLOAK_URL}/auth/admin/realms/{KEYCLOAK_REALM}{path}"


def _http_post_form(url: str, data: Dict[str, str], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=encoded, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        logger.warning(
            "Keycloak HTTPError %s on POST %s: %s",
            getattr(exc, "code", "?"), url, body,
        )
        raise


def _http_get(url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        logger.warning(
            "Keycloak HTTPError %s on GET %s: %s",
            getattr(exc, "code", "?"), url, body,
        )
        raise


def _http_post(url: str, headers: Optional[Dict[str, str]] = None) -> None:
    req = urllib.request.Request(url, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as _resp:
            return None
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        logger.warning(
            "Keycloak HTTPError %s on POST %s: %s",
            getattr(exc, "code", "?"), url, body,
        )
        raise


def _http_delete(url: str, headers: Optional[Dict[str, str]] = None) -> None:
    req = urllib.request.Request(url, headers=headers or {}, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as _resp:
            return None
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        logger.warning(
            "Keycloak HTTPError %s on DELETE %s: %s",
            getattr(exc, "code", "?"), url, body,
        )
        raise


def _get_admin_token() -> str:
    if not KEYCLOAK_ADMIN_CLIENT_ID:
        raise ValueError("KEYCLOAK_ADMIN_CLIENT_ID is not configured")
    if not KEYCLOAK_ADMIN_USERNAME:
        raise ValueError("KEYCLOAK_ADMIN_USERNAME is not configured")
    if not KEYCLOAK_ADMIN_PASSWORD:
        raise ValueError("KEYCLOAK_ADMIN_PASSWORD is not configured")

    token_url = (
        f"{KEYCLOAK_URL}/auth/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    )
    payload = {
        "grant_type": "password",
        "client_id": KEYCLOAK_ADMIN_CLIENT_ID,
        "username": KEYCLOAK_ADMIN_USERNAME,
        "password": KEYCLOAK_ADMIN_PASSWORD,
    }
    logger.debug(
        "Requesting Keycloak admin token url=%s grant_type=%s client_id=%s username=%s",
        token_url, payload["grant_type"], payload["client_id"], payload["username"],
    )
    data = _http_post_form(token_url, payload)
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("Keycloak admin token response did not include access_token")
    return access_token


def find_keycloak_user_id_by_email(admin_token: str, email: str) -> Optional[str]:
    query = urllib.parse.urlencode({"email": email, "exact": "true"})
    url = f"{_build_admin_url('/users')}?{query}"
    users = _http_get(url, headers={"Authorization": f"Bearer {admin_token}"})
    if not users:
        return None
    user = next((u for u in users if u.get("email", "").lower() == email.lower()), users[0])
    return str(user.get("id", "")) or None


def list_keycloak_user_sessions(admin_token: str, user_id: str) -> List[Dict[str, Any]]:
    url = _build_admin_url(f"/users/{urllib.parse.quote(user_id, safe='')}/sessions")
    sessions = _http_get(url, headers={"Authorization": f"Bearer {admin_token}"})
    if not isinstance(sessions, list):
        return []
    return [s for s in sessions if isinstance(s, dict)]


def delete_keycloak_session(admin_token: str, session_id: str) -> None:
    url = _build_admin_url(f"/sessions/{urllib.parse.quote(session_id, safe='')}")
    _http_delete(url, headers={"Authorization": f"Bearer {admin_token}"})


def logout_keycloak_user(admin_token: str, user_id: str) -> None:
    url = _build_admin_url(f"/users/{urllib.parse.quote(user_id, safe='')}/logout")
    _http_post(url, headers={"Authorization": f"Bearer {admin_token}"})


def terminate_keycloak_sessions_by_email(email: Optional[str]) -> None:
    if not email or not KEYCLOAK_URL or not KEYCLOAK_REALM:
        return

    admin_token = None
    try:
        admin_token = _get_admin_token()
    except Exception as exc:
        logger.warning("Failed to obtain Keycloak admin token: %s", exc)
        return

    try:
        user_id = find_keycloak_user_id_by_email(admin_token, email)
    except Exception as exc:
        logger.warning("Failed to find Keycloak user by email: %s", exc)
        return

    if not user_id:
        return

    try:
        sessions = list_keycloak_user_sessions(admin_token, user_id)
    except Exception as exc:
        logger.warning("Failed to list Keycloak sessions: %s", exc)
        return

    if not sessions:
        return

    try:
        logout_keycloak_user(admin_token, user_id)
    except Exception as exc:
        logger.warning("Failed to logout Keycloak user sessions: %s", exc)
        return


def terminate_keycloak_sessions_by_user_id(user_id: str) -> None:
    """Best-effort Keycloak logout for a Nexent user.

    Resolves the user's email from the local user_tenant record, then
    terminates the corresponding Keycloak sessions via Admin API.
    """
    if not KEYCLOAK_URL or not KEYCLOAK_REALM:
        return

    email = None
    try:
        user_tenant = get_user_tenant_by_user_id(user_id)
        if user_tenant:
            email = user_tenant.get("user_email")
    except Exception as exc:
        logger.warning("Failed to resolve email for Keycloak logout: %s", exc)

    if not email:
        return

    try:
        terminate_keycloak_sessions_by_email(email)
    except Exception as exc:
        logger.warning("Failed to terminate Keycloak sessions: %s", exc)
