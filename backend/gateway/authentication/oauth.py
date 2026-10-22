# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Dict

import jwt
from consts.const import SUPABASE_JWT_SECRET
from contracts.constants.identity import OAUTH_PENDING_PURPOSE
from contracts.authentication import PendingOAuthIdentity
from contracts.errors.exceptions import OAuthLinkError, OAuthProviderError


def parse_pending_oauth_token(pending_token: str) -> PendingOAuthIdentity:
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


def parse_state(state: str) -> Dict[str, str]:
    parts = state.split(":", 2)
    if len(parts) >= 2:
        return {
            "provider": parts[0],
            "token": parts[1],
            "link_user_id": parts[2] if len(parts) > 2 else "",
        }
    return {"provider": state, "token": "", "link_user_id": ""}
