# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reject unknown exposures before CORS, credential lookup or upstream work."""

from starlette.responses import JSONResponse

from infrastructure.security.identity import DELEGATION_PATH


class ExposureMiddleware:
    def __init__(self, app, *, registry):
        self.app, self.registry = app, registry

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope.get("method", "GET")
        local = scope["type"] == "http" and (
            method == "GET" and path in {"/health/live", "/health/ready"}
            or method == "POST" and path == DELEGATION_PATH)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        if method == "OPTIONS" and b"origin" in headers and b"access-control-request-method" in headers:
            method = headers[b"access-control-request-method"].decode("latin-1")
        match = self.registry.match(method, path, transport="websocket" if scope["type"] == "websocket" else "http",
                                    raw_path=scope.get("raw_path"))
        if (local and scope.get("raw_path", path.encode()) == path.encode()) or match:
            scope["gateway.exposure"] = match
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        await JSONResponse({"detail": "Not found"}, status_code=404)(scope, receive, send)
