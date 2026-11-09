# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant MCP dispatch with delegated Gateway authentication and local authorization."""

import logging
import re
from typing import Any, Callable, Dict

from infrastructure.service_identity.context import identity_context
from infrastructure.service_identity.credential_client import resolve_mcp_identity

logger = logging.getLogger(__name__)


class TenantMCPRouter:
    """Dispatch /mcp/{tenant_id}/... requests to the tenant's MCP app."""

    def __init__(self, *, get_app, refresh, internal_token, gateway_required, legacy_identity=None):
        self.get_app = get_app
        self.refresh = refresh
        self.internal_token = internal_token
        self.gateway_required = gateway_required
        self.legacy_identity = legacy_identity

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        path = scope.get("path", "")
        match = re.match(r"^/mcp/([^/]+)(/.*)?$", path)
        if not match:
            await _send_not_found(send)
            return

        tenant_id = match.group(1)
        headers = scope.get("headers", [])
        if sum(name.lower() == b"authorization" for name, _ in headers) > 1:
            await _send_forbidden(send)
            return
        request_headers = {name.lower(): value for name, value in headers}
        principal = None
        authorization = request_headers.get(b"authorization")
        requested_tenant = request_headers.get(b"x-tenant-id", b"").decode()
        internal_token = request_headers.get(b"x-nexent-internal-token", b"").decode()
        if not authorization and (requested_tenant != tenant_id or not self.internal_token or internal_token != self.internal_token):
            await _send_forbidden(send)
            return
        if authorization:
            try:
                if self.gateway_required:
                    principal = await resolve_mcp_identity(scope, authorization.decode("latin-1"))
                    authenticated_tenant_id = principal["tenant_id"]
                else:
                    _, authenticated_tenant_id = self.legacy_identity(authorization.decode("latin-1"))
            except Exception:
                await _send_forbidden(send)
                return
            if str(authenticated_tenant_id) != tenant_id:
                await _send_forbidden(send)
                return

        app = self.get_app(tenant_id)
        if app is None:
            try:
                self.refresh(tenant_id)
            except Exception:
                logger.exception("Failed to lazily initialize MCP tenant %s", tenant_id)
                await _send_not_found(send)
                return
            app = self.get_app(tenant_id)
        if app is None:
            await _send_not_found(send)
            return

        delegated_scope = dict(scope)
        delegated_scope["path"] = match.group(2) or "/"
        delegated_scope["root_path"] = f"{scope.get('root_path', '')}/mcp/{tenant_id}"
        context_token = identity_context.set(principal)
        try:
            await app(delegated_scope, receive, send)
        finally:
            identity_context.reset(context_token)


async def _send_not_found(send: Callable) -> None:
    await send({"type": "http.response.start", "status": 404, "headers": []})
    await send({"type": "http.response.body", "body": b"MCP tenant not found"})


async def _send_forbidden(send: Callable) -> None:
    await send({"type": "http.response.start", "status": 403, "headers": []})
    await send({"type": "http.response.body", "body": b"MCP tenant access denied"})

