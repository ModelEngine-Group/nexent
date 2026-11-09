# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""MCP's signed delegation client; external credentials are verified by Gateway."""

import json
from urllib.parse import urlsplit

import httpx

from service_common.security.identity import DELEGATION_PATH, IdentityError, sign_delegation, verify_identity
from service_common.service_identity.gateway import signing_key


async def resolve_mcp_identity(scope, authorization, *, gateway_url=None, key=None, transport=None):
    if gateway_url is None:
        from contracts.constants.environment import GATEWAY_SERVICE_URL

        gateway_url = GATEWAY_SERVICE_URL
    origin = urlsplit(gateway_url)
    if (origin.scheme not in {"http", "https"} or not origin.netloc or origin.username or origin.password
            or origin.path not in {"", "/"} or origin.query or origin.fragment):
        raise IdentityError("Invalid Gateway origin")
    key = signing_key() if key is None else key
    method, path, query = scope.get("method", "GET"), scope["path"], scope.get("query_string", b"")
    body = json.dumps({"authorization": authorization, "method": method, "path": path,
                       "query": query.hex()}, separators=(",", ":"), sort_keys=True).encode()
    try:
        async with httpx.AsyncClient(transport=transport, timeout=10, trust_env=False, follow_redirects=False) as client:
            response = await client.post(gateway_url.rstrip("/") + DELEGATION_PATH, content=body,
                                         headers={"content-type": "application/json",
                                                  "x-nexent-service-token": sign_delegation(body, key=key)})
        if response.status_code != 200:
            raise IdentityError("Gateway credential delegation failed")
        return verify_identity(response.json()["identity_token"], "mcp", method, path, query, key=key)
    except (httpx.RequestError, ValueError, TypeError, KeyError) as exc:
        raise IdentityError("Gateway credential delegation failed") from exc
