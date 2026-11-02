# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""External credential verification without business or persistence imports."""

import jwt
from gateway.security.token_codec import decode_session

from gateway.security.policy import canonical_path, is_public_request
from gateway.security.identity import IdentityError, bearer_token
from gateway.security.management_client import IdentityUnavailable, lookup_identity


def authorization_for(connection):
    if len(connection.headers.getlist("authorization")) > 1:
        raise IdentityError("Ambiguous authorization headers")
    header = connection.headers.get("authorization")
    if header:
        return header
    if not canonical_path(connection.url.path).startswith("/nb/"):
        cookie = connection.cookies.get("nexent_access_token")
        if cookie:
            return "Bearer " + cookie
    return None


async def resolve_identity(connection, client, management_url, *, settings):
    if connection.scope.get("method", "GET") == "POST" and canonical_path(connection.url.path) == "/user/logout":
        # Verified logout identity is needed for CAS revocation; invalid logout
        # credentials must retain the existing idempotent anonymous outcome.
        try:
            return await _resolve_identity(connection, client, management_url, settings=settings)
        except (IdentityError, IdentityUnavailable):
            return None
    return await _resolve_identity(connection, client, management_url, settings=settings)


async def _resolve_identity(connection, client, management_url, *, settings):
    method = connection.scope.get("method", "GET")
    path = canonical_path(connection.url.path)
    authorization = authorization_for(connection)
    # Bootstrap callbacks carry their own one-time tickets/pending tokens.
    optional_session = path in {"/user/current_user_info", "/user/session", "/user/logout"}
    if is_public_request(method, path) and not (optional_session and authorization):
        return None
    language = connection.cookies.get("NEXT_LOCALE", "zh")
    language = language if language in {"zh", "en"} else "zh"
    if not path.startswith("/nb/") and settings.is_speed_mode:
        return {"user_id": settings.default_user_id, "tenant_id": settings.default_tenant_id, "role": "SPEED", "language": language, "kind": "session"}
    token = bearer_token(authorization)
    if not token:
        raise IdentityError("Authentication required")
    if path.startswith("/nb/"):
        payload = {"kind": "api_key", "access_key": token, "language": language}
    else:
        if not settings.jwt_secret:
            raise IdentityUnavailable("Session verifier is not configured")
        try:
            claims = decode_session(token, key=settings.jwt_secret, issuer=settings.jwt_issuer)
            if claims.get("purpose") or claims.get("scope"):
                raise IdentityError("Invalid session policy")
            if not isinstance(claims["sub"], str) or not claims["sub"].strip() or type(claims["ver"]) is not int:
                raise IdentityError("Invalid session identity")
        except (jwt.InvalidTokenError, TypeError, ValueError) as exc:
            raise IdentityError("Invalid session credential") from exc
        payload = {"kind": "session", "user_id": claims["sub"], "token_version": claims["ver"],
                   "session_id": claims.get("sid"), "language": language}
    return await lookup_identity(payload, client, management_url, key=settings.signing_key())
