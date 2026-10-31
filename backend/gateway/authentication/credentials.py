# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""External credential verification without business or persistence imports."""

import json

import httpx
import jwt

from contracts.authentication_routes import canonical_path, is_public_request
from contracts.constants import environment
from infrastructure.security.gateway_identity import IdentityError, bearer_token, sign_lookup


class IdentityUnavailable(RuntimeError):
    """The authoritative identity service could not be reached safely."""


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


async def resolve_identity(connection, client, management_url):
    method = connection.scope.get("method", "GET")
    path = canonical_path(connection.url.path)
    authorization = authorization_for(connection)
    # Bootstrap callbacks carry their own one-time tickets/pending tokens.
    optional_session = path in {"/user/current_user_info", "/user/session"}
    if is_public_request(method, path) and not (optional_session and authorization):
        return None
    language = connection.cookies.get("NEXT_LOCALE", "zh")
    language = language if language in {"zh", "en"} else "zh"
    if not path.startswith("/nb/") and environment.IS_SPEED_MODE:
        from contracts.constants.constants import DEFAULT_USER_ID, DEFAULT_TENANT_ID

        return {"user_id": DEFAULT_USER_ID, "tenant_id": DEFAULT_TENANT_ID, "role": "SPEED", "language": language, "kind": "session"}
    token = bearer_token(authorization)
    if not token:
        raise IdentityError("Authentication required")
    if path.startswith("/nb/"):
        payload = {"kind": "api_key", "access_key": token, "language": language}
    else:
        if not environment.JWT_SECRET:
            raise IdentityUnavailable("Session verifier is not configured")
        try:
            claims = jwt.decode(token, environment.JWT_SECRET, algorithms=["HS256"],
                                issuer=environment.JWT_ISSUER, audience="authenticated",
                                options={"require": ["sub", "iat", "exp", "ver"]})
            if claims.get("purpose") or claims.get("scope"):
                raise IdentityError("Invalid session policy")
            if not isinstance(claims["sub"], str) or not claims["sub"].strip() or type(claims["ver"]) is not int:
                raise IdentityError("Invalid session identity")
        except (jwt.InvalidTokenError, TypeError, ValueError) as exc:
            raise IdentityError("Invalid session credential") from exc
        payload = {"kind": "session", "user_id": claims["sub"], "token_version": claims["ver"],
                   "session_id": claims.get("sid"), "language": language}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    try:
        response = await client.post(management_url.rstrip("/") + "/api/internal/identity/resolve",
                                     content=body, headers={"content-type": "application/json",
                                                           "x-nexent-service-token": sign_lookup(body)},
                                     timeout=httpx.Timeout(10))
    except httpx.RequestError as exc:
        raise IdentityUnavailable("Identity service unavailable") from exc
    if response.status_code in {401, 403}:
        raise IdentityError("Invalid or revoked credential")
    if response.status_code != 200:
        raise IdentityUnavailable("Identity service unavailable")
    try:
        identity = response.json()
        if (not isinstance(identity, dict) or identity.get("kind") != payload["kind"]
                or any(not isinstance(identity.get(k), str) or not identity[k] for k in ("user_id", "tenant_id"))):
            raise ValueError("Invalid identity response")
        if payload["kind"] == "session" and identity["user_id"] != payload["user_id"]:
            raise ValueError("Identity mismatch")
        return identity
    except (ValueError, TypeError) as exc:
        raise IdentityUnavailable("Invalid identity service response") from exc
