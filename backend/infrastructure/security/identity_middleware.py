# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Downstream HTTP/WS signature boundary with request-local identity lifetime."""

from starlette.responses import JSONResponse

from gateway.protocol.routes import canonical_path
from infrastructure.security.service_routes import is_runtime_service_request
from infrastructure.security.gateway_identity import (
    IDENTITY_HEADER, LOOKUP_PATH, IdentityError, enabled, identity_context, signing_key, verify_identity,
)


class GatewayIdentityMiddleware:
    def __init__(self, app, *, audience, required=None):
        self.app, self.audience = app, audience
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
        if scope["type"] == "http" and method == "OPTIONS" and "origin" in headers and "access-control-request-method" in headers:
            return await self.app(scope, receive, send)
        if self.audience == "management" and method == "POST" and path == LOOKUP_PATH:
            # The private endpoint verifies a body-bound service token itself.
            return await self.app(scope, receive, send)
        try:
            if self.audience == "runtime" and is_runtime_service_request(method, path):
                from infrastructure.security.internal_tokens import verify_internal_runtime_jwt

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
