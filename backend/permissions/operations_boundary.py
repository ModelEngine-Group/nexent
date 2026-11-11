# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restrict operations-only identities at the shared business HTTP boundary."""

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from contracts.errors.exceptions import TokenExpiredError, UnauthorizedError
from gateway.authentication.auth import get_current_user_context

# These existing endpoints only maintain the caller's own authenticated session.
SESSION_PATHS = frozenset(
    {
        "/user/current_user_info",
        "/user/current_user_id",
        "/user/session",
        "/user/logout",
        "/user/revoke",
        "/user/refresh_token",
        "/user/password",
    }
)
BOOTSTRAP_PATHS = frozenset({"/tenant_config/deployment_version", "/user/cas/config", "/user/oauth/config"})


def install_operations_boundary(app):
    @app.middleware("http")
    async def operations_boundary(request, call_next):
        authorization = request.headers.get("authorization")
        if authorization:
            try:
                _, _, roles = await run_in_threadpool(get_current_user_context, authorization)
            except (UnauthorizedError, TokenExpiredError):
                # Each existing route retains its credential policy and error envelope.
                return await call_next(request)
            path = request.scope.get("path", "")
            root = request.scope.get("root_path", "")
            if root and path.startswith(root + "/"):
                path = path[len(root) :]
            bootstrap = request.method == "GET" and path in BOOTSTRAP_PATHS
            if set(roles) == {"OPS"} and path not in SESSION_PATHS and not bootstrap and not path.startswith("/ops/"):
                return JSONResponse(
                    status_code=403, content={"message": "Operations-only identity cannot access business APIs"}
                )
        return await call_next(request)
