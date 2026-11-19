# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Casdoor authorization-code authentication with browser-bound state and PKCE."""

import base64
import hashlib
import json
import secrets
import ssl
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

import jwt

from consts import const as settings
from contracts.constants.environment import (
    JWT_SECRET,
    OAUTH_CA_BUNDLE,
    OAUTH_CALLBACK_BASE_URL,
    OAUTH_SSL_VERIFY,
)
from contracts.errors.exceptions import OAuthProviderError

FLOW_COOKIE_NAME = "nexent_casdoor_flow"
FLOW_TTL_SECONDS = 1800
LINK_FLOW_TTL_SECONDS = 600
_FLOW_AUDIENCE = "casdoor-login"


class CasdoorFlowExpired(OAuthProviderError):
    """A browser must restart authorization before the provider can be contacted."""


def flow_ttl(link_user_id: str) -> int:
    return LINK_FLOW_TTL_SECONDS if link_user_id else FLOW_TTL_SECONDS


def _callback_url() -> str:
    return f"{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=casdoor"


def subject_key(subject: str) -> str:
    """Return the stable binding key scoped to the configured identity service."""
    return hashlib.sha256(f"{settings.CASDOOR_ENDPOINT}\0{subject}".encode()).hexdigest()


def create_authorization(link_user_id: str = "", *, signup: bool = False) -> tuple[str, str]:
    """Return the public redirect and a signed, browser-only flow cookie."""
    if not settings.is_casdoor_enabled() or not JWT_SECRET or not OAUTH_CALLBACK_BASE_URL:
        raise OAuthProviderError("Casdoor login is not configured")
    now = int(time.time())
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    cookie = jwt.encode(
        {
            "aud": _FLOW_AUDIENCE,
            "iat": now,
            "exp": now + flow_ttl(link_user_id),
            "state": state,
            "verifier": verifier,
            "link_user_id": link_user_id,
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    params = {
        "client_id": settings.CASDOOR_CLIENT_ID,
        "redirect_uri": _callback_url(),
        "response_type": "code",
        "scope": "openid profile email",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    page = "signup" if signup else "login"
    return f"{settings.CASDOOR_ENDPOINT}/{page}/oauth/authorize?{urlencode(params)}", cookie


def validate_flow(state: str, cookie: str) -> dict[str, Any]:
    """Reject foreign, expired or modified flows before contacting the provider."""
    try:
        if state and not cookie:
            raise CasdoorFlowExpired("Casdoor authorization flow has expired or is no longer available")
        if not state or not JWT_SECRET:
            raise ValueError("Missing browser flow")
        flow = jwt.decode(
            cookie,
            JWT_SECRET,
            algorithms=["HS256"],
            audience=_FLOW_AUDIENCE,
            options={"require": ["exp", "iat", "aud", "state", "verifier"]},
        )
        if (
            not isinstance(flow["state"], str)
            or not secrets.compare_digest(flow["state"], state)
            or not isinstance(flow["verifier"], str)
            or not 43 <= len(flow["verifier"]) <= 128
            or not isinstance(flow.get("link_user_id", ""), str)
        ):
            raise ValueError("Invalid browser flow")
        return flow
    except jwt.ExpiredSignatureError as exc:
        raise CasdoorFlowExpired("Casdoor authorization flow has expired or is no longer available") from exc
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise OAuthProviderError("Invalid or expired Casdoor login flow") from exc


def _request_json(url: str, *, data: dict | None = None, headers: dict | None = None) -> dict:
    """Perform a bounded provider request without leaking response details in errors."""
    request_headers = {"Accept": "application/json", **(headers or {})}
    body = None
    if data is not None:
        body = urlencode(data).encode()
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers=request_headers)
    try:
        context = ssl.create_default_context(cafile=OAUTH_CA_BUNDLE or None)
        if not OAUTH_SSL_VERIFY:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(request, timeout=15, context=context) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("Invalid provider response")
        return result
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise OAuthProviderError("Casdoor authentication request failed") from exc


def authenticate(code: str, flow: dict[str, Any]) -> dict[str, str]:
    """Exchange a code on the backend and map the authenticated userinfo subject."""
    if not settings.is_casdoor_enabled() or not code:
        raise OAuthProviderError("Casdoor login is not configured or code is missing")
    endpoint = settings.CASDOOR_BACKEND_ENDPOINT or settings.CASDOOR_ENDPOINT
    token = _request_json(
        f"{endpoint}/api/login/oauth/access_token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.CASDOOR_CLIENT_ID,
            "client_secret": settings.CASDOOR_CLIENT_SECRET,
            "code": code,
            "redirect_uri": _callback_url(),
            "code_verifier": flow["verifier"],
        },
    )
    access_token = token.get("access_token")
    if token.get("error") or not isinstance(access_token, str) or not access_token:
        raise OAuthProviderError("Casdoor authorization code exchange failed")
    user = _request_json(f"{endpoint}/api/userinfo", headers={"Authorization": f"Bearer {access_token}"})
    subject = user.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise OAuthProviderError("Casdoor returned no stable user identity")
    email = user.get("email")
    username = user.get("preferred_username") or user.get("name")
    return {
        "id": subject_key(subject),
        "email": email if isinstance(email, str) else "",
        "username": username if isinstance(username, str) else "",
    }
