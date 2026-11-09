# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authenticate the AgentOS namespace before dispatching to Runtime routes."""

from starlette.responses import JSONResponse

from contracts.agentos import BODY_KEY, MAX_REQUEST_BYTES, NAMESPACE, PRINCIPAL_KEY, CompatibilityOperation
from gateway.security.context import identity_context
from infrastructure.agentos_identity import AgentOSIdentityError, verify_call


class AgentOSMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if path.startswith("/api/"):
            path = path.removeprefix("/api")
        if not path.startswith(NAMESPACE):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        try:
            operation = CompatibilityOperation(path)
        except ValueError:
            return await self._error(scope, receive, send, 404, "AGENTOS_OPERATION_NOT_FOUND")
        if scope["method"] != "POST" or scope["query_string"]:
            return await self._error(scope, receive, send, 400, "AGENTOS_INVALID_REQUEST")

        authorization = [value for name, value in scope["headers"] if name == b"authorization"]
        if len(authorization) != 1:
            return await self._error(scope, receive, send, 401, "AGENTOS_UNAUTHORIZED")
        scheme, _, token = authorization[0].decode("latin-1").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return await self._error(scope, receive, send, 401, "AGENTOS_UNAUTHORIZED")

        buffer = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            buffer.extend(message.get("body", b""))
            if len(buffer) > MAX_REQUEST_BYTES:
                return await self._error(scope, receive, send, 413, "AGENTOS_REQUEST_TOO_LARGE")
            if not message.get("more_body", False):
                break
        body = bytes(buffer)
        try:
            principal = verify_call(token, operation, body)
        except AgentOSIdentityError:
            return await self._error(scope, receive, send, 401, "AGENTOS_UNAUTHORIZED")

        # Preserve ASGI body semantics for middleware downstream of this boundary.
        async def replay_body():
            nonlocal pending_body
            if pending_body:
                pending_body = False
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        pending_body = True
        authenticated_scope = {**scope, PRINCIPAL_KEY: principal, BODY_KEY: body}
        reset = identity_context.set(
            {"user_id": principal.user_id, "tenant_id": principal.tenant_id, "kind": "internal"}
        )
        try:
            await self.app(authenticated_scope, replay_body, send)
        finally:
            identity_context.reset(reset)

    @staticmethod
    async def _error(scope, receive, send, status, code):
        await JSONResponse({"code": code}, status_code=status)(scope, receive, send)
