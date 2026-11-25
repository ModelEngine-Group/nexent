# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Downstream HTTP/WS signature boundary with request-local identity lifetime."""

import os

from starlette.responses import JSONResponse

from contracts.agentos import MANAGEMENT_OPERATION_PATHS, PRINCIPAL_KEY
from gateway.identity.policy import canonical_path
from gateway.identity.downstream import (
    IDENTITY_HEADER, LOOKUP_PATH, IdentityError, enabled, identity_context, signing_key, verify_identity,
)

# Comma-separated canonical path prefixes that bypass the gateway identity check.
# Intended for local-dev demo endpoints (e.g. an OpenAPI→MCP sample service) that the
# MCP runtime calls with a plain HTTP request and no service signature. Empty by default,
# so production behavior is unchanged unless an operator opts in.
_PUBLIC_PATH_PREFIXES: tuple[str, ...] = tuple(
    prefix.strip()
    for prefix in os.environ.get("GATEWAY_IDENTITY_PUBLIC_PATHS", "").split(",")
    if prefix.strip()
)


class GatewayIdentityMiddleware:
    def __init__(self, app, *, audience, required=None, internal_runtime_request=None):
        self.app, self.audience = app, audience
        self.internal_runtime_request = internal_runtime_request
        self.required = enabled() if required is None else required
        if self.required:
            signing_key()

    async def __call__(self, scope, receive, send):
        if not self.required or scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        method = scope.get("method", "GET")
        path = canonical_path(scope["path"])
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        if path in {"/health/live", "/health/ready"}:
            return await self.app(scope, receive, send)
        if _PUBLIC_PATH_PREFIXES and any(
            path == prefix or path.startswith(prefix + "/") for prefix in _PUBLIC_PATH_PREFIXES
        ):
            # Operator-allowlisted demo/public endpoints (GATEWAY_IDENTITY_PUBLIC_PATHS).
            return await self.app(scope, receive, send)
        if scope["type"] == "http" and method == "OPTIONS" and "origin" in headers and "access-control-request-method" in headers:
            return await self.app(scope, receive, send)
        if self.audience == "management" and method == "POST" and (
            path == LOOKUP_PATH or path in MANAGEMENT_OPERATION_PATHS
        ):
            # These private endpoints verify their own body-bound service token.
            return await self.app(scope, receive, send)
        if self.audience == "runtime" and PRINCIPAL_KEY in scope:
            # AgentOSMiddleware already checked the operation and exact body.
            return await self.app(scope, receive, send)
        if (self.audience == "runtime" and scope["type"] == "http"
                and method == "POST" and path == "/internal/sandbox/tool-invoke"):
            # The owner Runtime's callback registry verifies the invocation capability.
            return await self.app(scope, receive, send)
        try:
            if (self.audience == "runtime" and self.internal_runtime_request is not None
                    and self.internal_runtime_request(method, path)):
                from gateway.identity.internal_tokens import verify_internal_runtime_jwt

                user_id, tenant_id = verify_internal_runtime_jwt(headers.get("authorization"))
                identity = {"user_id": user_id, "tenant_id": tenant_id, "kind": "internal"}
            else:
                identity = verify_identity(headers.get(IDENTITY_HEADER, ""), self.audience,
                                           method, scope["path"], scope.get("query_string", b""))
        except Exception as exc:
            # Only authentication failures become 401; unexpected programming errors propagate.
            from contracts.errors.exceptions import UnauthorizedError

            if not isinstance(exc, (IdentityError, UnauthorizedError)):
                raise
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await JSONResponse({"message": "Gateway identity required or invalid"}, status_code=401)(scope, receive, send)
            return
        token = identity_context.set(identity)
        try:
            await self.app(scope, receive, send)
        finally:
            identity_context.reset(token)
