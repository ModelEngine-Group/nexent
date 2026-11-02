# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private MCP credential delegation through the Gateway session policy."""

import json

from starlette.requests import Request

from gateway.security.credentials import resolve_identity
from gateway.security.identity import DELEGATION_PATH, IdentityError, sign_identity, verify_delegation


async def delegate_mcp(request, client, management_url, *, settings):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise IdentityError("Delegation request too large")
    if len(request.headers.getlist("x-nexent-service-token")) != 1:
        raise IdentityError("Delegation signature required")
    verify_delegation(request.headers["x-nexent-service-token"], bytes(body), key=settings.signing_key())
    try:
        data = json.loads(body)
        authorization, method, path = (data[field] for field in ("authorization", "method", "path"))
        query = bytes.fromhex(data["query"])
        authorization_bytes = authorization.encode("latin-1")
        if (not isinstance(authorization, str) or not authorization
                or method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
                or not isinstance(path, str) or not path.startswith("/mcp/")):
            raise ValueError("Invalid delegation input")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise IdentityError("Invalid delegation input") from exc
    # The caller cannot select an anonymous bootstrap or API-key policy.
    connection = Request({"type": "http", "method": "POST", "scheme": "http",
                          "path": "/api/_delegated/session", "query_string": b"",
                          "headers": [(b"authorization", authorization_bytes)]})
    principal = await resolve_identity(connection, client, management_url, settings=settings)
    return {"identity_token": sign_identity(principal, "mcp", method, path, query, key=settings.signing_key())}
