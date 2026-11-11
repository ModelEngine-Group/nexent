# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restrict operations-only identities at the shared business HTTP boundary."""

import re

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from contracts.errors.exceptions import TokenExpiredError, UnauthorizedError
from gateway.authentication.auth import get_current_user_context
from permissions.rbac import has_permission

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


# Some existing list and detail endpoints use POST with a read-only request body.
RESOURCE_READ_POSTS = frozenset({
    "/users/list", "/groups/list", "/model/manage/list", "/model/manage/healthcheck",
    "/invitations/list", "/agent/search_info",
})
RESOURCE_READ_GETS = frozenset({
    "/api-keys", "/agent/list", "/model/capacity-coverage", "/monitoring/models",
    "/indices", "/indices/health", "/skills",
    "/mcp/list", "/mcp/containers", "/mcp/tools", "/mcp/healthcheck", "/tool/openapi_services",
    "/tag-libraries", "/capacity/personal/users", "/capacity/personal/summary",
    "/capacity/personal/default-quota",
})
# Combined roles use their ordinary read behavior for general business views
# unless the request explicitly targets the authenticated tenant.
SHARED_READ_PATHS = frozenset({
    "/agent/list", "/agent/search_info", "/indices", "/skills",
    "/mcp/list", "/mcp/containers", "/mcp/tools", "/mcp/healthcheck", "/tool/openapi_services",
})
RESOURCE_READ_PATH = re.compile(
    r"/(?:tenants/[^/]+(?:/quota/usage)?|groups/[0-9]+/members|"
    r"agent/[0-9]+/versions|summary/[^/]+/summary|tag-libraries/[0-9]+/definitions|"
    r"capacity/personal/users/[^/]+/kbs|mcp/container/[^/]+/logs)"
)


def is_resource_read(method: str, path: str) -> bool:
    if method == "POST":
        return path in RESOURCE_READ_POSTS
    return method == "GET" and (path in RESOURCE_READ_GETS or RESOURCE_READ_PATH.fullmatch(path) is not None)


def install_operations_boundary(app):
    @app.middleware("http")
    async def operations_boundary(request, call_next):
        path = request.scope.get("path", "")
        root = request.scope.get("root_path", "")
        if root and path.startswith(root + "/"):
            path = path[len(root) :]
        authorization = request.headers.get("authorization")
        needs_session = (
            (request.method == "POST" and path == "/groups/list")
            or (request.method == "GET" and (
                path.startswith("/summary/") and path.endswith("/summary")
                or re.fullmatch(r"/groups/[0-9]+/members", path) is not None
            ))
        )
        if needs_session and not authorization:
            return JSONResponse(status_code=401, content={"message": "Authentication required"})
        if authorization:
            try:
                _, tenant_id, roles = await run_in_threadpool(get_current_user_context, authorization)
            except (UnauthorizedError, TokenExpiredError):
                if needs_session:
                    return JSONResponse(status_code=401, content={"message": "Authentication required"})
                # Each existing route retains its credential policy and error envelope.
                return await call_next(request)
            role_set = set(roles)
            targets = request.query_params.getlist("tenant_id")
            uses_inventory = role_set == {"OPS"} or path not in SHARED_READ_PATHS or tenant_id in targets
            if (
                "OPS" in role_set
                and not role_set.intersection({"ADMIN", "SU"})
                and uses_inventory
                and is_resource_read(request.method, path)
            ):
                allowed = await run_in_threadpool(has_permission, roles, "resource.inventory:read")
                if not allowed or not tenant_id or any(target and target != tenant_id for target in targets):
                    return JSONResponse(status_code=403, content={"message": "Resource reads are limited to your tenant"})
                request.state.resource_read_tenant = tenant_id
                return await call_next(request)

            bootstrap = request.method == "GET" and path in BOOTSTRAP_PATHS
            if role_set == {"OPS"} and path not in SESSION_PATHS and not bootstrap and not path.startswith("/ops/"):
                return JSONResponse(
                    status_code=403, content={"message": "Operations-only identity cannot access business APIs"}
                )
        return await call_next(request)
